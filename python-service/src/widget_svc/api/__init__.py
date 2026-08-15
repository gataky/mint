"""The HTTP transport: two ASGI apps, one per listener."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware import Middleware

from widget_svc.api import health as health_routes
from widget_svc.api import problem, widgets
from widget_svc.api.health import Health
from widget_svc.api.middleware import (
    AccessLogMiddleware,
    RequestContextMiddleware,
    TimeoutMiddleware,
)
from widget_svc.config import Config
from widget_svc.service import Widgets

__all__ = ["create_admin", "create_api"]


def create_api(config: Config, service: Widgets) -> FastAPI:
    """The public API: the widget routes, OpenAPI 3.1, and Swagger UI at /docs."""
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
            # tracing and metrics belong here, outside the access log.
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


def create_admin(config: Config, health: Health) -> FastAPI:
    """The admin surface: liveness, readiness, and later /metrics.

    Deliberately not access-logged and not under the request timeout — a
    readiness probe every second would drown the log.
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
    problem.install(app)
    return app
