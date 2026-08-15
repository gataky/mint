"""The HTTP transport: two ASGI apps, one per listener."""

from __future__ import annotations

from fastapi import FastAPI, Response
from starlette.middleware import Middleware

from widget_svc.api import health as health_routes
from widget_svc.api import problem, widgets
from widget_svc.api.health import Health
from widget_svc.api.middleware import (
    AccessLogMiddleware,
    MetricsMiddleware,
    RequestContextMiddleware,
    TimeoutMiddleware,
)
from widget_svc.config import Config
from widget_svc.observability import CONTENT_TYPE as METRICS_CONTENT_TYPE
from widget_svc.observability import Metrics
from widget_svc.service import Widgets

__all__ = ["create_admin", "create_api"]


def create_api(config: Config, service: Widgets, metrics: Metrics | None = None) -> FastAPI:
    """The public API: the widget routes, OpenAPI 3.1, and Swagger UI at /docs.

    metrics may be None, which omits the instrumentation — useful in tests that
    do not care about it.
    """
    instrumentation = (
        [Middleware(MetricsMiddleware, metrics=metrics)] if metrics is not None else []
    )

    app = FastAPI(
        title=config.service.name,
        version=config.service.version,
        description="Widget service. Generated from the Mint template.",
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

    app.state.widgets = service
    app.include_router(widgets.router)
    problem.install(app)
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
