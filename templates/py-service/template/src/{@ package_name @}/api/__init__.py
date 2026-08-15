"""The HTTP transport: two ASGI apps, one per listener."""

from __future__ import annotations

from fastapi import FastAPI, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.middleware import Middleware

from {@ package_name @}.api import health as health_routes
{% if include_examples %}from {@ package_name @}.api import orders as order_routes
from {@ package_name @}.api import problem, widgets
{% else %}from {@ package_name @}.api import problem
{% endif %}from {@ package_name @}.api.health import Health
from {@ package_name @}.api.middleware import (
    AccessLogMiddleware,
    MetricsMiddleware,
    RequestContextMiddleware,
    TimeoutMiddleware,
)
from {@ package_name @}.config import Config
from {@ package_name @}.observability import CONTENT_TYPE as METRICS_CONTENT_TYPE
from {@ package_name @}.observability import Metrics
{% if include_examples %}from {@ package_name @}.service import Orders, Widgets
{% endif %}
__all__ = ["create_admin", "create_api"]


def create_api(
    config: Config,
{% if include_examples %}    widget_service: Widgets,
    order_service: Orders,
{% endif %}    metrics: Metrics | None = None,
) -> FastAPI:
{% if include_examples %}    """The public API: the widget routes, OpenAPI 3.1, and Swagger UI at /docs.
{% else %}    """The public API: OpenAPI 3.1, and Swagger UI at /docs.
{% endif %}
    metrics may be None, which omits the instrumentation — useful in tests that
    do not care about it.
    """
    instrumentation = (
        [Middleware(MetricsMiddleware, metrics=metrics)] if metrics is not None else []
    )

    app = FastAPI(
        title=config.service.name,
        version=config.service.version,
        description="{@ service_description @}",
        docs_url="/docs",
        openapi_url="/openapi.json",
        # The first entry is the outermost. See middleware.py for why this
        # order is what it is.
        middleware=[
            Middleware(RequestContextMiddleware),
            # tracing belongs here, outside metrics and the access log.
            *instrumentation,
            Middleware(AccessLogMiddleware),
            # auth belongs here: after observation, before execution.
            Middleware(
                TimeoutMiddleware,
                timeout_seconds=config.server.request_timeout.total_seconds(),
            ),
        ],
        # FastAPI's default 422 body is not RFC 9457; problem.install replaces it.
        redoc_url=None,
    )

{% if include_examples %}    app.state.widgets = widget_service
    app.state.orders = order_service

    # One router per resource. Each lives in its own module alongside this one.
    app.include_router(widgets.router)
    app.include_router(order_routes.router)
{% else %}    # One router per resource. Each lives in its own module alongside this one.
    # app.state.things = thing_service
    # app.include_router(things.router)
{% endif %}
    problem.install(app)

    # Adds OpenTelemetryMiddleware at the outside of the stack, so the spans it
    # starts are visible to the metrics and access-log middleware within.
    # Span names come from the route template, matching the metrics label and
    # the Go service's span names.
    #
    # This is always installed: when tracing is disabled the global provider is
    # a no-op and no spans are recorded, which is cheaper than branching here.
    FastAPIInstrumentor.instrument_app(
        app,
        # Without this the ASGI instrumentation emits an "http send" and an
        # "http receive" child span per request, describing the ASGI protocol
        # rather than anything a reader of the trace cares about. The Go service
        # produces one server span per request; this makes the exported traces
        # comparable.
        exclude_spans=["receive", "send"],
    )

    return app


def create_admin(config: Config, health: Health, metrics: Metrics | None = None) -> FastAPI:
    """The admin surface: liveness, readiness and /metrics.

    Deliberately not instrumented, not access-logged, and not under the request
    timeout — a readiness probe every second and a scrape every fifteen would be
    most of both the log volume and the metrics.
    """
    app = FastAPI(
        title=f"{config.service.name} (admin)",
        version=config.service.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        middleware=[Middleware(RequestContextMiddleware)],
    )

    app.state.health = health
    app.include_router(health_routes.router)

    if metrics is not None:

        @app.get("/metrics", include_in_schema=False)
        async def scrape() -> Response:
            return Response(content=metrics.render(), media_type=METRICS_CONTENT_TYPE)

    problem.install(app)
    return app
