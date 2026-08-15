"""The service entrypoint.

This module is the composition root: the only place that decides what is wired
to what. It contains no business logic and no HTTP handling.

Run it with ``python -m widget_svc``, never the ``uvicorn`` CLI — the CLI
configures logging before importing the app, which would put uvicorn's own
handlers back.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI

from widget_svc import config as config_module
from widget_svc.api import create_admin, create_api
from widget_svc.api.health import Health
from widget_svc.config import Config
from widget_svc.log import configure as configure_logging
from widget_svc.log import logger
from widget_svc.observability import Metrics
from widget_svc.service import Widgets


@dataclass(slots=True)
class Listener:
    """One named HTTP server to run."""

    name: str
    port: int
    app: FastAPI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="widget-svc")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print the effective configuration and exit",
    )
    args = parser.parse_args(argv)

    # Startup order is fixed: config, then logging, then the service, then the
    # health registry, then the listeners. Nothing observable starts before
    # there is a logger to record it.
    try:
        config = config_module.load()
    except Exception as exc:
        # The logger may not exist yet, so startup failures go to stderr
        # directly. Fail fast and loudly.
        print(f"fatal: {exc}", file=sys.stderr)
        return 1

    if args.print_config:
        print(config_module.render(config))
        return 0

    configure_logging(
        level=config.logging.level,
        fmt=config.logging.format,
        service=config.service.name,
        service_version=config.service.version,
        env=config.env,
    )

    logger.info("starting", split_listeners=config.split_listeners())

    if config.env != "local":
        # The middleware chain has a reserved, empty auth slot. Authentication
        # is expected at a gateway or mesh; this makes the deferral mechanical
        # rather than remembered.
        logger.warning(
            "no authentication middleware is registered",
            expectation="authentication is handled by an upstream gateway or mesh",
        )

    widgets = Widgets()
    health = Health()
    metrics = Metrics(config)

    try:
        asyncio.run(serve(config, listeners(config, widgets, health, metrics), health))
    except Exception as exc:
        logger.opt(exception=exc).error("fatal")
        return 1
    return 0


def listeners(config: Config, widgets: Widgets, health: Health, metrics: Metrics) -> list[Listener]:
    """The listeners to run.

    When ``admin_port`` equals ``port`` the two apps collapse onto a single
    listener, which must keep working: it is how the service runs where only one
    port is available.

    Splitting them by default buys drain visibility, not security — any client
    that can reach the pod IP can reach every container port. Mid-drain, a split
    admin port still answers ``/readyz`` with 503 "draining" and still serves a
    final metrics scrape; collapsed onto one listener, both become
    connection-refused.
    """
    api = create_api(config, widgets, metrics)
    admin = create_admin(config, health, metrics)

    if not config.split_listeners():
        api.mount("/", admin)
        return [Listener("combined", config.server.port, api)]

    return [
        Listener("api", config.server.port, api),
        Listener("admin", config.server.admin_port, admin),
    ]


async def serve(config: Config, to_run: list[Listener], health: Health) -> None:
    """Run every listener until a signal arrives, then drain.

    ``uvicorn.run()`` is deliberately not used. It builds exactly one Server and
    exposes no handle on which to neutralize signal capture, so two of them race
    on the same handlers and the process dies before it drains. Constructing the
    servers here — and owning SIGTERM here — is what makes the split-port
    configuration shut down cleanly.
    """
    servers = []
    for listener in to_run:
        settings = uvicorn.Config(
            listener.app,
            host="0.0.0.0",
            port=listener.port,
            # Losing either of these silently restores uvicorn's own log
            # handlers, and the symptom appears nowhere near this line. The
            # access log comes from AccessLogMiddleware.
            log_config=None,
            access_log=False,
            timeout_keep_alive=int(config.server.idle_timeout.total_seconds()),
            timeout_graceful_shutdown=int(config.server.shutdown_timeout.total_seconds()),
        )
        server = uvicorn.Server(settings)
        # Signals are owned below, in one place. Two servers each installing
        # their own handlers is how a process dies before it drains.
        server.capture_signals = contextlib.nullcontext  # type: ignore[method-assign,assignment]
        servers.append(server)

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)

    tasks = [
        asyncio.create_task(server.serve(), name=listener.name)
        for server, listener in zip(servers, to_run, strict=True)
    ]
    for listener in to_run:
        logger.info("listening", listener=listener.name, addr=f"0.0.0.0:{listener.port}")

    await asyncio.wait(
        [*tasks, asyncio.create_task(stopping.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    logger.info(
        "shutdown signal received, draining",
        timeout=config_module.format_duration(config.server.shutdown_timeout),
    )

    # Fail readiness first. A load balancer needs to see /readyz go unhealthy
    # before connections stop being accepted, or it keeps routing traffic into a
    # closing socket.
    health.drain()

    for server in servers:
        server.should_exit = True

    done, pending = await asyncio.wait(
        tasks, timeout=config.server.shutdown_timeout.total_seconds()
    )
    for task in pending:
        task.cancel()
    if pending:
        raise TimeoutError(f"{len(pending)} listener(s) did not drain in time")

    for task in done:
        task.result()  # re-raise anything a listener failed with

    # When tracing lands, the tracer provider is flushed here — after the drain,
    # before the process exits. Final-request spans are lost otherwise.


if __name__ == "__main__":
    raise SystemExit(main())
