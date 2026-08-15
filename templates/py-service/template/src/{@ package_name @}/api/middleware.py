"""The request middleware chain.

Order, outermost first::

    recovery -> request-id -> [tracing] -> metrics -> logging -> [auth] -> timeout -> handler

Bracketed entries are not built yet. Their positions are what matters:

* tracing sits outside metrics and logging so both can carry the trace ID it
  put on the context, and so a span covers the whole request.
* auth sits **inside** logging and metrics — observe everything, then authorize,
  then execute. An access log that omits rejected requests is a success log; it
  cannot answer "401s are spiking, from where?". The accepted cost is that an
  unauthenticated flood drives log volume.
* auth sits **outside** timeout, because the request deadline is the handler's
  budget, not the authorizer's.

Recovery is not in this module: Starlette's ``ServerErrorMiddleware`` already
sits outermost, and :func:`{@ package_name @}.api.problem.install` gives it a handler.
Adding a recovery middleware here would only shadow it.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_504_GATEWAY_TIMEOUT
from starlette.types import ASGIApp

from {@ package_name @}.api.problem import problem
from {@ package_name @}.api.route import resolve_route
from {@ package_name @}.log import logger
from {@ package_name @}.observability import Metrics

#: Carries the request correlation ID in and out.
REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a correlation ID and binds it to the logging context.

    An inbound ID is reused so a caller's ID survives the hop, and it is echoed
    on the response.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        # contextualize is contextvar-based, so anything logged anywhere inside
        # this block carries request_id without being handed a logger.
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records the three HTTP server metrics.

    Sits outside the access log so both observe the same requests, and inside
    tracing so a future exemplar can carry the trace ID.
    """

    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        super().__init__(app)
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()

        # The in-flight gauge is labelled by method alone, because the route is
        # not known until the router has run. See resolve_route.
        self.metrics.request_started(request.method)
        try:
            response = await call_next(request)
        except BaseException:
            # The gauge must come down even when the handler raises, or it
            # climbs by one on every failure and never returns to zero.
            self.metrics.request_finished(
                request.method,
                resolve_route(request.scope),
                500,
                time.perf_counter() - started,
            )
            raise

        self.metrics.request_finished(
            request.method,
            resolve_route(request.scope),
            response.status_code,
            time.perf_counter() - started,
        )
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emits one structured line per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        # The route *template*, not the concrete path: /widgets/abc and
        # /widgets/def are one series, not two.
        route = resolve_route(request.scope)

        log = logger.bind(
            method=request.method,
            route=route,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
        if response.status_code >= 500:
            log.error("request")
        elif response.status_code >= 400:
            log.warning("request")
        else:
            log.info("request")

        return response


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Bounds how long a request may take.

    This is where the two services legitimately differ. Go puts a deadline on
    the context and trusts the handler to observe it, with the server's
    write timeout as the backstop; asyncio can cancel the task outright, so a
    hung handler is actually interrupted here and the client gets a 504 rather
    than a dropped connection.
    """

    def __init__(self, app: ASGIApp, timeout_seconds: float = 10.0) -> None:
        super().__init__(app)
        self.timeout_seconds = timeout_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await call_next(request)
        except TimeoutError:
            logger.warning(
                "request timed out",
                method=request.method,
                path=request.url.path,
                timeout_seconds=self.timeout_seconds,
            )
            return problem(
                request,
                HTTP_504_GATEWAY_TIMEOUT,
                f"request exceeded the {self.timeout_seconds:g}s deadline",
            )
