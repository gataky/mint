"""The client.

One class. It sends a request to a configured peer and returns the response, or
raises something from :mod:`mint_client.errors`. Everything it does beyond that
— trace context, correlation ID, the deadline, the metrics — happens because it
happened for every other call too, not because the call site asked.

What is automatic
-----------------
* **W3C trace context** is injected inside the client span, so the peer's server
  span is a child of *this attempt* rather than of the request that caused it.
* **``X-Request-Id``** is forwarded from the inbound request, so one ID spans a
  whole fan-out and one grep finds all of it.
* **The deadline** is inherited: a call takes what is left of the request
  budget, not a fresh allowance of its own.
* **Metrics** are recorded per attempt, under the peer's name.
* **RFC 9457** bodies are parsed off failures and attached to the exception.

What is not
-----------
No retries, no backoff, no circuit breaker — see :mod:`mint_client.resilience`
for why, and for where they go.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self, TypeVar, overload
from urllib.parse import urlsplit, urlunsplit

import httpx2
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind, Status, StatusCode
from pydantic import TypeAdapter, ValidationError

from mint_client import context
from mint_client.config import ClientsConfig, PoolConfig, TimeoutConfig
from mint_client.errors import (
    ConnectError,
    DeadlineExceededError,
    MintClientError,
    ResponseValidationError,
    TransportError,
    upstream_error_for,
)
from mint_client.observability import ERROR_STATUS, ClientMetrics
from mint_client.problem import parse_problem
from mint_client.version import __version__

__all__ = ["REQUEST_ID_HEADER", "Client", "Response"]

#: Re-exported so a caller never has to ``import httpx2`` to type a variable.
#: The client owning the transport choice is the point; leaking the import
#: everywhere would make changing it a repo-wide edit.
Response = httpx2.Response

#: The same header the service's RequestContextMiddleware reads and echoes.
REQUEST_ID_HEADER = "X-Request-Id"

T = TypeVar("T")

#: What ``into=`` accepts: a model class, a bare type, a generic alias such as
#: ``list[Widget]``, or a pre-built ``TypeAdapter`` for anything else.
type Into[U] = type[U] | TypeAdapter[U]

_tracer = trace.get_tracer("mint-client", __version__)


class Client:
    """An async HTTP client bound to exactly one peer.

    One instance per upstream service, built once at startup and shared: it owns
    a connection pool, and building one per call throws away every keep-alive
    connection and every bit of the pool's usefulness.

    Bound to *one* peer on purpose. A client that could address anywhere would
    have no honest ``peer`` label to put on its metrics, no single timeout
    policy, and no pool whose limits mean anything.
    """

    def __init__(
        self,
        *,
        peer: str,
        base_url: str,
        timeout: TimeoutConfig | None = None,
        pool: PoolConfig | None = None,
        headers: Mapping[str, str] | None = None,
        metrics: ClientMetrics | None = None,
        user_agent: str = "",
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.peer = peer
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout or TimeoutConfig()
        self._metrics = metrics

        limits = pool or PoolConfig()
        default_headers = {
            "User-Agent": _user_agent(user_agent),
            # Mint services speak JSON. Saying so costs nothing and makes a
            # misrouted request fail as a 406 rather than as an HTML page that
            # fails to parse three frames later.
            "Accept": "application/json, application/problem+json",
            **(headers or {}),
        }

        self._http = httpx2.AsyncClient(
            base_url=self.base_url,
            headers=default_headers,
            timeout=httpx2.Timeout(
                connect=self._timeout.connect.total_seconds(),
                read=self._timeout.read.total_seconds(),
                write=self._timeout.write.total_seconds(),
                pool=self._timeout.pool.total_seconds(),
            ),
            limits=httpx2.Limits(
                max_connections=limits.max_connections,
                max_keepalive_connections=limits.max_keepalive_connections,
                keepalive_expiry=limits.keepalive_expiry.total_seconds(),
            ),
            # Off by default, and deliberately. Between services a redirect is
            # almost always a misconfiguration — a missing trailing slash, a
            # http->https bounce — and following it silently converts a loud
            # 307 into a working call that costs two round trips forever. It
            # also drops the body on some redirect chains.
            follow_redirects=False,
            # The environment configures nothing here. Honouring HTTP_PROXY and
            # friends would let a variable nobody declared change where a call
            # goes, which is the same disease `make config` exists to cure.
            trust_env=False,
            transport=transport,
        )

        self._adapters: dict[Any, TypeAdapter[Any]] = {}

    @classmethod
    def for_peer(
        cls,
        clients: ClientsConfig,
        peer: str,
        *,
        metrics: ClientMetrics | None = None,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> Self:
        """Build a client for a peer named in the registry.

        Raises :class:`~mint_client.errors.UnknownPeerError` if it is not declared —
        at startup, which is when the composition root calls this, and not at
        the first call in production.
        """
        config = clients.peer(peer)
        return cls(
            peer=clients.peer_name(peer),
            base_url=config.base_url,
            timeout=clients.timeout_for(config),
            pool=clients.pool_for(config),
            headers=config.headers,
            metrics=metrics,
            user_agent=clients.user_agent,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Close the connection pool.

        The composition root calls this on shutdown, after the drain — sockets
        held open by a pool keep the peer's side allocated too.
        """
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- the verbs ---------------------------------------------------------
    #
    # Each is a thin, typed front door onto `request`. They exist rather than
    # making callers pass a method string because `client.get(...)` is what the
    # call site means, and because the overloads that make `into=` type
    # correctly have to be written per-method anyway.

    @overload
    async def get(self, path: str, *, into: Into[T], **kwargs: Any) -> T: ...
    @overload
    async def get(self, path: str, *, into: None = None, **kwargs: Any) -> Response: ...

    async def get(self, path: str, *, into: Into[T] | None = None, **kwargs: Any) -> T | Response:
        """GET."""
        return await self.request("GET", path, into=into, **kwargs)

    @overload
    async def post(self, path: str, *, into: Into[T], **kwargs: Any) -> T: ...
    @overload
    async def post(self, path: str, *, into: None = None, **kwargs: Any) -> Response: ...

    async def post(self, path: str, *, into: Into[T] | None = None, **kwargs: Any) -> T | Response:
        """POST."""
        return await self.request("POST", path, into=into, **kwargs)

    @overload
    async def put(self, path: str, *, into: Into[T], **kwargs: Any) -> T: ...
    @overload
    async def put(self, path: str, *, into: None = None, **kwargs: Any) -> Response: ...

    async def put(self, path: str, *, into: Into[T] | None = None, **kwargs: Any) -> T | Response:
        """PUT."""
        return await self.request("PUT", path, into=into, **kwargs)

    @overload
    async def patch(self, path: str, *, into: Into[T], **kwargs: Any) -> T: ...
    @overload
    async def patch(self, path: str, *, into: None = None, **kwargs: Any) -> Response: ...

    async def patch(self, path: str, *, into: Into[T] | None = None, **kwargs: Any) -> T | Response:
        """PATCH."""
        return await self.request("PATCH", path, into=into, **kwargs)

    @overload
    async def delete(self, path: str, *, into: Into[T], **kwargs: Any) -> T: ...
    @overload
    async def delete(self, path: str, *, into: None = None, **kwargs: Any) -> Response: ...

    async def delete(
        self, path: str, *, into: Into[T] | None = None, **kwargs: Any
    ) -> T | Response:
        """DELETE."""
        return await self.request("DELETE", path, into=into, **kwargs)

    async def head(self, path: str, **kwargs: Any) -> Response:
        """HEAD. There is no body, so there is nothing for ``into=`` to bind."""
        return await self.request("HEAD", path, into=None, **kwargs)

    # -- the engine --------------------------------------------------------

    # The overloads spell the parameters out rather than using **kwargs, because
    # an overload that accepts more than the implementation does is not a valid
    # overload — mypy rejects it, and it would let a typo through as a keyword
    # argument that silently went nowhere.

    @overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        into: Into[T],
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        route: str = "",
    ) -> T: ...

    @overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        into: None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        route: str = "",
    ) -> Response: ...

    async def request(
        self,
        method: str,
        path: str,
        *,
        into: Into[T] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        route: str = "",
    ) -> T | Response:
        """Send one request.

        :param into: bind the response body to this type and return it. Without
            it you get the :class:`Response` and can call ``.json()`` yourself.
        :param timeout_seconds: override the total budget for this call. It
            can only ever tighten the deadline, never extend it past what the
            inbound request has left.
        :param route: the route *template*, e.g. ``/widgets/{id}``. Used for the
            span name and ``http.route``, matching how the server side names its
            spans. Never used as a metric label.

        :raises UpstreamError: the peer answered with a 4xx or 5xx.
        :raises TransportError: no response was received.
        :raises ResponseValidationError: ``into=`` was given and did not fit.
        """
        response = await self._send(
            method=method.upper(),
            path=path,
            params=params,
            json=json,
            content=content,
            headers=headers,
            timeout_seconds=timeout_seconds,
            route=route,
        )

        if into is None:
            return response
        return self._bind(response, into, method=method.upper(), path=path)

    async def _send(self, **attempt: Any) -> Response:
        """Execute the call.

        Today this is one attempt. It is a separate method from
        :meth:`_send_once` so that a retry policy becomes a loop *here* and
        changes nothing else — see :mod:`mint_client.resilience`.
        """
        return await self._send_once(**attempt)

    async def _send_once(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        json: Any,
        content: bytes | str | None,
        headers: Mapping[str, str] | None,
        timeout_seconds: float | None,
        route: str,
    ) -> Response:
        """One attempt: one span, one set of metric observations."""
        span_name = f"{method} {route}" if route else method

        outgoing: dict[str, str] = dict(headers or {})
        correlation_id = context.request_id()
        if correlation_id:
            outgoing.setdefault(REQUEST_ID_HEADER, correlation_id)

        started = time.perf_counter()
        if self._metrics is not None:
            self._metrics.request_started(method, self.peer)

        with _tracer.start_as_current_span(
            span_name,
            kind=SpanKind.CLIENT,
            attributes=self._span_attributes(method, path, route),
        ) as span:
            # Injected *inside* the span, so the peer's server span is a child
            # of this attempt. Injecting before the span starts would parent the
            # peer to whatever span happened to be current, which on a retry is
            # the wrong one.
            inject(outgoing)

            try:
                # The budget check is inside the instrumented region on purpose.
                # A call abandoned for having no time left is still a failed
                # outbound call, and a service constantly blowing its deadline
                # must not show up in a dashboard as making no calls at all.
                budget = self._budget(method=method, path=path, timeout_seconds=timeout_seconds)

                # asyncio.timeout is the only thing that bounds the call as a
                # whole. httpx's per-phase timeouts each restart with their
                # phase, so a peer dribbling one byte per second satisfies a
                # read timeout indefinitely.
                async with asyncio.timeout(budget):
                    response = await self._http.request(
                        method,
                        path,
                        params=params,
                        json=json,
                        content=content,
                        headers=outgoing,
                    )
            except BaseException as exc:
                elapsed = time.perf_counter() - started
                if self._metrics is not None:
                    self._metrics.request_finished(method, self.peer, ERROR_STATUS, elapsed)
                translated = self._transport_error(exc, span, method=method, path=path)
                if translated is exc:
                    # Already one of ours, or not ours at all. Re-raising it as
                    # its own __cause__ would put the same frame in the
                    # traceback twice.
                    raise
                raise translated from exc

            elapsed = time.perf_counter() - started
            if self._metrics is not None:
                self._metrics.request_finished(
                    method, self.peer, str(response.status_code), elapsed
                )

            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 400:
                # OpenTelemetry's HTTP convention: for a CLIENT span, any 4xx or
                # 5xx is an error. (For a SERVER span only 5xx is — a 404 is the
                # server working correctly, and the caller's problem.)
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", str(response.status_code))
                raise self._upstream_error(response, method=method, path=path)

            return response

    # -- the parts that are worth naming -----------------------------------

    def _budget(self, *, method: str, path: str, timeout_seconds: float | None) -> float:
        """The number of seconds this call may take.

        The tightest of: the caller's override, the peer's configured total, and
        whatever is left of the inbound request's budget. A call that already
        has no time left is failed *without dialling* — opening a connection
        that is certain to be abandoned costs the peer a worker and this process
        a socket, and the caller learns nothing they did not already know.
        """
        allowance = (
            timeout_seconds if timeout_seconds is not None else self._timeout.total.total_seconds()
        )

        left = context.remaining()
        if left is None:
            return allowance

        if left <= 0:
            raise DeadlineExceededError(
                "request budget exhausted before the call was made",
                peer=self.peer,
                method=method,
                path=path,
            )
        return min(allowance, left)

    def _span_attributes(self, method: str, path: str, route: str) -> dict[str, Any]:
        """The OpenTelemetry HTTP client attributes for this call."""
        split = urlsplit(self.base_url)
        attributes: dict[str, Any] = {
            "http.request.method": method,
            "url.full": _redact(f"{self.base_url}{path}"),
            "server.address": split.hostname or "",
            "peer.service": self.peer,
        }
        if split.port is not None:
            attributes["server.port"] = split.port
        if route:
            attributes["http.route"] = route
        return attributes

    def _transport_error(
        self,
        exc: BaseException,
        span: trace.Span,
        *,
        method: str,
        path: str,
    ) -> BaseException:
        """Translate a transport failure, or hand back anything that is not one.

        Cancellation is deliberately passed through untouched. A ``CancelledError``
        that arrives from outside means the *caller* is being torn down, and
        converting it into an ordinary exception is how a task refuses to die.
        """
        if isinstance(exc, asyncio.CancelledError):
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", "cancelled")
            return exc

        kind = type(exc).__name__
        span.set_status(Status(StatusCode.ERROR))
        span.set_attribute("error.type", kind)

        if isinstance(exc, MintClientError):
            # Already translated — the budget check raises DeadlineExceededError
            # from inside the try. It still belongs on the span, which is why
            # this branch is here and not before the attributes above.
            return exc

        if isinstance(exc, TimeoutError | httpx2.TimeoutException):
            # asyncio.timeout raises TimeoutError; httpx raises its own for the
            # per-phase ones. Both mean the same thing to a caller.
            return DeadlineExceededError(
                f"timed out after {self._timeout.total.total_seconds():g}s",
                peer=self.peer,
                method=method,
                path=path,
                cause=exc,
            )

        if isinstance(exc, httpx2.ConnectError | httpx2.ProxyError | httpx2.UnsupportedProtocol):
            return ConnectError(
                f"could not connect: {exc}",
                peer=self.peer,
                method=method,
                path=path,
                cause=exc,
            )

        if isinstance(exc, httpx2.HTTPError):
            return TransportError(
                f"{kind}: {exc}", peer=self.peer, method=method, path=path, cause=exc
            )

        # Not ours. A bug in this process, or a KeyboardInterrupt.
        return exc

    def _upstream_error(self, response: Response, *, method: str, path: str) -> BaseException:
        """Build the exception for a 4xx or 5xx."""
        problem = parse_problem(response.headers.get("content-type", ""), response.content)

        # The peer's own detail if it sent one; otherwise its reason phrase.
        # Never the response body verbatim — an upstream returning an HTML error
        # page would otherwise put a whole document into an exception message.
        message = str(problem) if problem is not None else response.reason_phrase

        return upstream_error_for(response.status_code)(
            message,
            status=response.status_code,
            peer=self.peer,
            method=method,
            path=path,
            problem=problem,
            request_id=response.headers.get(REQUEST_ID_HEADER, ""),
            retry_after=_retry_after(response.headers.get("retry-after")),
        )

    def _bind(self, response: Response, into: Into[T], *, method: str, path: str) -> T:
        """Validate the response body into the requested type."""
        adapter = self._adapter(into)
        try:
            return adapter.validate_json(response.content)
        except ValidationError as exc:
            raise ResponseValidationError(
                f"upstream response did not match {_name(into)}: {exc.error_count()} error(s)",
                peer=self.peer,
                method=method,
                path=path,
                status=response.status_code,
                cause=exc,
            ) from exc

    def _adapter(self, into: Into[T]) -> TypeAdapter[T]:
        """Cache the TypeAdapter for a type.

        Building one is not free — it compiles a validator — and a client that
        rebuilt it per call would pay that on every request forever.
        """
        if isinstance(into, TypeAdapter):
            return into
        try:
            cached = self._adapters.get(into)
        except TypeError:  # an unhashable annotation
            return TypeAdapter(into)
        if cached is None:
            cached = TypeAdapter(into)
            self._adapters[into] = cached
        return cached


def _user_agent(service: str) -> str:
    """``widget-svc/0.1.0 mint-client/0.1.0``, or just the library when unset.

    Naming the library as well as the service is what lets a peer's operator
    tell "a Mint service is calling me" from "something is calling me", which
    matters the first time an unexpected caller shows up in an access log.
    """
    library = f"mint-client/{__version__}"
    return f"{service} {library}".strip() if service else library


def _redact(url: str) -> str:
    """Strip credentials from a URL before it becomes a span attribute.

    OpenTelemetry requires it for ``url.full``, and a span exporter is one of
    the easier places to accidentally publish a password.
    """
    split = urlsplit(url)
    if "@" not in split.netloc:
        return url
    _, _, host = split.netloc.rpartition("@")
    return urlunsplit(split._replace(netloc=f"REDACTED:REDACTED@{host}"))


def _retry_after(value: str | None) -> float | None:
    """Parse ``Retry-After``, which RFC 9110 allows in two entirely different forms.

    Nothing in this library acts on the result — it is attached to the exception
    so a caller's own policy can. Anything unparseable is ``None``: a peer
    sending nonsense should not turn a 429 into a crash.
    """
    if not value:
        return None

    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(text)
    except TypeError, ValueError:
        return None
    if when is None:
        return None

    import datetime as _datetime

    now = _datetime.datetime.now(tz=when.tzinfo or _datetime.UTC)
    return max(0.0, (when - now).total_seconds())


def _name(into: Into[Any]) -> str:
    """A readable name for a type, for an error message."""
    if isinstance(into, TypeAdapter):
        return str(into)
    return getattr(into, "__name__", None) or str(into)
