"""The metrics registry and, later, the tracer provider.

Nothing else in the service talks to Prometheus or OpenTelemetry directly.

**Phase 1 assumes a single worker.** ``prometheus_client``'s multiprocess mode
needs ``PROMETHEUS_MULTIPROC_DIR`` and ``multiprocess_mode="livesum"`` on the
in-flight gauge; without them, running more than one uvicorn worker makes that
gauge report one worker's view rather than the process group's.
"""

from __future__ import annotations

from collections.abc import Sequence

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
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


class Tracing:
    """Owns the tracer provider and knows how to shut it down."""

    def __init__(self, provider: TracerProvider | None, *, exporting: bool) -> None:
        self.provider = provider
        self.exporting = exporting

    def shutdown(self) -> None:
        """Flush and stop the tracer provider.

        This must run after the drain and before the process exits: the spans
        for the last requests served sit in the batch processor's queue, and are
        silently lost otherwise.
        """
        if self.provider is not None:
            self.provider.shutdown()


def configure_tracing(config: Config) -> Tracing:
    """Build the tracer provider and install it globally.

    **A real provider is installed even with no collector configured.** The
    exporter is what becomes a no-op, not the tracer: spans are still created,
    so every log line still carries a trace_id and a request can still be
    followed through the logs — while a fresh ``make run`` emits no
    connection-refused retries. Disabling the tracer instead would silently drop
    trace_id from the logs, which is the thing most worth having locally.
    """
    if not config.observability.tracing.enabled:
        # Explicitly off. No spans at all, so no trace_id anywhere.
        set_global_textmap(TraceContextTextMapPropagator())
        return Tracing(None, exporting=False)

    # Mint owns identity. OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES are
    # deliberately not consulted: logs and spans disagreeing about service or
    # env would break the error-to-trace path.
    resource = Resource(
        attributes={
            "service.name": config.service.name,
            "service.version": config.service.version,
            "service.owner": config.service.owner,
            "deployment.environment.name": config.env,
        }
    )

    exporter, exporting = _span_exporter(config.observability.tracing.otlp_endpoint)
    provider = TracerProvider(
        resource=resource,
        # ParentBased so an upstream sampling decision is respected; the ratio
        # applies only to traces this service starts.
        sampler=ParentBased(TraceIdRatioBased(config.observability.tracing.sample_ratio)),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    # W3C trace context, so a trace survives the hop between services
    # regardless of which language each one is written in.
    set_global_textmap(TraceContextTextMapPropagator())

    return Tracing(provider, exporting=exporting)


def _span_exporter(endpoint: str) -> tuple[SpanExporter, bool]:
    """Return the span exporter and whether it actually exports."""
    if not endpoint.strip():
        return _DiscardExporter(), False
    return OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"), True


class _DiscardExporter(SpanExporter):
    """Accepts spans and drops them.

    Used when no collector is configured, so that spans — and therefore trace
    IDs on log lines — still exist locally without anything trying to reach the
    network.
    """

    # The argument names are fixed by the SpanExporter interface and callers
    # may pass them by keyword, so they are kept rather than underscored.
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:  # noqa: ARG002
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True
