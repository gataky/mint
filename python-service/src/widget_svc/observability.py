"""The metrics registry and, later, the tracer provider.

Nothing else in the service talks to Prometheus or OpenTelemetry directly.

**Phase 1 assumes a single worker.** ``prometheus_client``'s multiprocess mode
needs ``PROMETHEUS_MULTIPROC_DIR`` and ``multiprocess_mode="livesum"`` on the
in-flight gauge; without them, running more than one uvicorn worker makes that
gauge report one worker's view rather than the process group's.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    disable_created_metrics,
    generate_latest,
)
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector

from widget_svc.config import Config

#: OpenTelemetry's advisory buckets for http.server.request.duration, declared
#: literally so both services use the same boundaries rather than each
#: library's default.
DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class Metrics:
    """The HTTP server instruments and the registry they live in.

    The instrumentation is hand-written over the raw primitives rather than
    using ``prometheus-fastapi-instrumentator``, which hardcodes ``handler`` and
    ``status`` as label names and groups status codes into ``2xx``. Neither
    matches the agreed label set.
    """

    def __init__(self, config: Config) -> None:
        # Every counter would otherwise be shadowed by a `_created` gauge
        # carrying its creation timestamp — noise in the exposition and not
        # something the Go service emits. Disabled through the API rather than
        # the PROMETHEUS_DISABLE_CREATED_SERIES environment variable, because
        # config is read in exactly one place and this is not it.
        disable_created_metrics()  # type: ignore[no-untyped-call]

        # A fresh registry, not the process-global REGISTRY: the global one
        # cannot be built twice, which makes it impossible to construct two
        # independent services in one test session.
        self.registry = CollectorRegistry()

        self.requests = Counter(
            "http_server_requests",  # _total is appended by the client
            "Total HTTP requests served.",
            labelnames=("method", "route", "status"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "http_server_request_duration_seconds",
            "HTTP request duration in seconds.",
            labelnames=("method", "route", "status"),
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        # No route label: the route is not known when a request starts.
        # OpenTelemetry's convention for http.server.active_requests omits it
        # for exactly that reason.
        self.active = Gauge(
            "http_server_active_requests",
            "HTTP requests currently in flight.",
            labelnames=("method",),
            registry=self.registry,
        )

        # service_owner is deliberately NOT a label on the metrics above. A
        # re-org would otherwise change the identity of every series and break
        # rate() across the boundary. It lives here instead, joinable with
        # Prometheus 3's info().
        target = Info(
            "target", "Metadata about the service exposing these metrics.", registry=self.registry
        )
        target.info(
            {
                "service_name": config.service.name,
                "service_version": config.service.version,
                "service_owner": config.service.owner,
                "deployment_environment_name": config.env,
            }
        )

        # Runtime and process metrics are language-specific by nature. They are
        # worth having; nothing compares them against the Go service.
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        GCCollector(registry=self.registry)

    def request_started(self, method: str) -> None:
        """Increment the in-flight gauge."""
        self.active.labels(method).inc()

    def request_finished(self, method: str, route: str, status: int, elapsed: float) -> None:
        """Decrement the in-flight gauge and record the outcome."""
        self.active.labels(method).dec()

        code = str(status)
        self.requests.labels(method, route, code).inc()
        self.duration.labels(method, route, code).observe(elapsed)

    def render(self) -> bytes:
        """The Prometheus exposition format, for the /metrics endpoint."""
        return generate_latest(self.registry)
