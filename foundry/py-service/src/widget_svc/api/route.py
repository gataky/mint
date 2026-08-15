"""Reading a request's route template."""

from __future__ import annotations

from starlette.types import Scope

#: The route label used when a request matched no registered route.
#:
#: It exists to bound cardinality. Labelling an unrouted request with its
#: concrete path would let anyone create unbounded series by sending requests to
#: random URLs.
UNMATCHED_ROUTE = "<unmatched>"


def resolve_route(scope: Scope) -> str:
    """Report the route template a request was dispatched to.

    Starlette records the matched route on the scope as it dispatches, so this
    is only meaningful *after* the request has been handled. That is why the
    in-flight gauge is not labelled by route: at the moment a request starts,
    nobody knows which route it belongs to. OpenTelemetry's own convention for
    ``http.server.active_requests`` omits the route for the same reason.

    Re-running the router's matching to learn the route early was tried and
    rejected: FastAPI wraps included routers in a private type whose shape
    changes between releases.
    """
    route = scope.get("route")
    path: str | None = getattr(route, "path", None)
    return path if path else UNMATCHED_ROUTE
