"""What a call raises when it does not return.

**This taxonomy is deliberately not the service's domain taxonomy.** It would
have been shorter to raise ``NotFoundError`` when an upstream returns 404 and
let it fall through the caller's ``api/problem.py`` untouched — and it would
have been wrong. That service's 404 means *the resource you asked me for does
not exist*. An upstream's 404 means *a thing I depend on is missing*, which is
frequently a 500, sometimes a 400, and only occasionally a 404.

So the client says what happened on the wire, and the caller's ``service/``
layer decides what it means::

    try:
        widget = await client.get(f"/widgets/{widget_id}", into=Widget)
    except UpstreamNotFoundError as exc:
        raise InvalidError(f'no widget with id "{widget_id}"') from exc

That translation is business logic, and business logic lives in ``service/``.

The split at the top of the tree is the one that matters operationally:

``TransportError``
    No response was received. The request may or may not have been executed —
    a read timeout says nothing about whether the peer applied the write.
``UpstreamError``
    A response was received and it was a failure. The peer definitely ran.
"""

from __future__ import annotations

from mint_client.problem import Problem

__all__ = [
    "ConnectError",
    "DeadlineExceededError",
    "MintClientError",
    "ResponseValidationError",
    "TransportError",
    "UnknownPeerError",
    "UpstreamClientError",
    "UpstreamConflictError",
    "UpstreamError",
    "UpstreamForbiddenError",
    "UpstreamInvalidError",
    "UpstreamNotFoundError",
    "UpstreamRateLimitedError",
    "UpstreamServerError",
    "UpstreamUnauthorizedError",
    "UpstreamUnavailableError",
    "UpstreamUnprocessableError",
    "upstream_error_for",
]


class MintClientError(Exception):
    """Base for everything this library raises.

    Carries where the call was going, so a log line or a traceback names the
    peer without the call site having to add it.
    """

    def __init__(
        self,
        message: str,
        *,
        peer: str = "",
        method: str = "",
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.peer = peer
        self.method = method
        self.path = path

    def __str__(self) -> str:
        target = f"{self.method} {self.peer}{self.path}".strip()
        return f"{target}: {self.message}" if target else self.message


class UnknownPeerError(MintClientError):
    """A peer name that is not in the configured registry.

    Raised at construction, not at first call — the whole point of declaring
    peers in config is that a typo fails at startup rather than at 3am under
    load.
    """


class TransportError(MintClientError):
    """The call did not produce a response.

    **Whether the peer executed the request is unknown.** A connect failure
    means it did not; a read timeout means it may have. Retrying a
    non-idempotent call after one of these can duplicate an effect — which is
    most of why retries are not switched on by default. See ``resilience.py``.
    """

    def __init__(
        self,
        message: str,
        *,
        peer: str = "",
        method: str = "",
        path: str = "",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, peer=peer, method=method, path=path)
        self.cause = cause


class ConnectError(TransportError):
    """DNS, TCP, TLS or proxy failure. The peer did not receive the request."""


class DeadlineExceededError(TransportError):
    """The call ran out of time.

    Raised both when a call exhausts its own timeout and when the inbound
    request's remaining budget is already spent — in the second case *without
    opening a connection*, because a call that cannot finish in time is a call
    worth not making.
    """


class ResponseValidationError(MintClientError):
    """The peer answered successfully, in a shape that is not what was asked for.

    This is an upstream contract violation, not a local bug and not a transport
    fault, so it gets its own type: it is the error that means "redeploy the
    other service" rather than "retry" or "fix this code".
    """

    def __init__(
        self,
        message: str,
        *,
        peer: str = "",
        method: str = "",
        path: str = "",
        status: int = 0,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, peer=peer, method=method, path=path)
        self.status = status
        self.cause = cause


class UpstreamError(MintClientError):
    """A 4xx or 5xx response.

    ``problem`` is the parsed RFC 9457 body when the peer sent one, and ``None``
    when it did not. It is never fabricated: an empty Problem and an absent one
    are different facts, and only one of them means "the upstream told us
    nothing".
    """

    #: Filled in by each subclass; ``0`` on the base, which is never raised.
    status: int = 0

    def __init__(
        self,
        message: str,
        *,
        status: int,
        peer: str = "",
        method: str = "",
        path: str = "",
        problem: Problem | None = None,
        request_id: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, peer=peer, method=method, path=path)
        self.status = status
        self.problem = problem
        #: The upstream's X-Request-Id. The single most useful thing to put in a
        #: log line when the failure has to be chased in someone else's service.
        self.request_id = request_id
        #: Seconds from the ``Retry-After`` header, when the peer sent a usable
        #: one. Nothing in this library acts on it; it is handed to the caller.
        self.retry_after = retry_after

    def __str__(self) -> str:
        target = f"{self.method} {self.peer}{self.path}".strip()
        parts = [f"{self.status}"]
        if self.message:
            parts.append(self.message)
        rendered = " ".join(parts)
        return f"{target}: {rendered}" if target else rendered


class UpstreamClientError(UpstreamError):
    """A 4xx. This service sent something the peer would not accept.

    Almost always a bug on this side, or a stale assumption about the peer's
    contract. Retrying the identical request will fail identically.
    """


class UpstreamServerError(UpstreamError):
    """A 5xx. The peer failed to handle a request it accepted."""


class UpstreamInvalidError(UpstreamClientError):
    """400 — a well-formed request that violated one of the peer's rules."""

    status = 400


class UpstreamUnauthorizedError(UpstreamClientError):
    """401 — no usable credentials reached the peer."""

    status = 401


class UpstreamForbiddenError(UpstreamClientError):
    """403 — credentials reached the peer and did not permit the action."""

    status = 403


class UpstreamNotFoundError(UpstreamClientError):
    """404 — the peer has no such resource, or no such route."""

    status = 404


class UpstreamConflictError(UpstreamClientError):
    """409 — the request collided with the peer's existing state."""

    status = 409


class UpstreamUnprocessableError(UpstreamClientError):
    """422 — the request body's *shape* was rejected.

    Distinct from 400 in exactly the way Mint services distinguish them: 422 is
    a schema violation, 400 is a business-rule violation. Seeing this from a
    Mint peer means the two services disagree about a model.
    """

    status = 422


class UpstreamRateLimitedError(UpstreamClientError):
    """429 — the peer is shedding load from this caller.

    ``retry_after`` carries the peer's own guidance when it sent any.
    """

    status = 429


class UpstreamUnavailableError(UpstreamServerError):
    """502, 503 or 504 — the peer, or something behind it, is not answering.

    The one upstream failure that is usually transient and usually worth
    retrying, which is why it is separable from a plain 500.
    """

    status = 503


#: Statuses with a name of their own. Anything else falls back to the 4xx/5xx
#: parent, so an unmapped status is still catchable by class rather than
#: arriving as a bare UpstreamError nobody has a handler for.
_BY_STATUS: dict[int, type[UpstreamError]] = {
    400: UpstreamInvalidError,
    401: UpstreamUnauthorizedError,
    403: UpstreamForbiddenError,
    404: UpstreamNotFoundError,
    409: UpstreamConflictError,
    422: UpstreamUnprocessableError,
    429: UpstreamRateLimitedError,
    502: UpstreamUnavailableError,
    503: UpstreamUnavailableError,
    504: UpstreamUnavailableError,
}


def upstream_error_for(status: int) -> type[UpstreamError]:
    """The most specific exception class for a status code."""
    named = _BY_STATUS.get(status)
    if named is not None:
        return named
    return UpstreamServerError if status >= 500 else UpstreamClientError
