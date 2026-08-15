"""Tracing: span naming, context propagation, and the log correlation fields."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.testclient import TestClient

from widget_svc.api import create_api
from widget_svc.config import Config
from widget_svc.log import KEY_SPAN_ID, KEY_TRACE_ID, logger
from widget_svc.service import Orders, Widgets


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Record spans in memory instead of exporting them."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # The global provider can only be set once per process, so this reaches
    # past the guard rather than fighting it.
    trace._TRACER_PROVIDER = provider
    yield exporter
    provider.shutdown()
    trace._TRACER_PROVIDER = None


@pytest.fixture
def traced(spans: InMemorySpanExporter, widgets: Widgets, orders: Orders) -> Iterator[TestClient]:
    with TestClient(create_api(Config(), widgets, orders)) as client:
        yield client


def ended(exporter: InMemorySpanExporter) -> tuple[ReadableSpan, ...]:
    return exporter.get_finished_spans()


def test_log_lines_carry_the_trace_and_span_id(
    traced: TestClient, spans: InMemorySpanExporter, logs: io.StringIO
) -> None:
    traced.get("/widgets")

    line = json.loads(logs.getvalue().strip().splitlines()[-1])
    assert line[KEY_TRACE_ID]
    assert line[KEY_SPAN_ID]

    # The ID on the log line must be the ID of the span that was actually
    # recorded, or the error-to-trace path leads nowhere.
    recorded = ended(spans)
    assert len(recorded) == 1
    assert format(recorded[0].context.trace_id, "032x") == line[KEY_TRACE_ID]


def test_trace_fields_are_omitted_without_a_span(logs: io.StringIO) -> None:
    # An empty trace_id is worse than an absent one: it looks like a trace that
    # exists and cannot be found.
    logger.info("no span here")

    line = json.loads(logs.getvalue().strip().splitlines()[-1])
    assert KEY_TRACE_ID not in line
    assert KEY_SPAN_ID not in line


def test_span_is_named_for_the_route_template(
    traced: TestClient, spans: InMemorySpanExporter
) -> None:
    traced.get("/widgets/abc123")

    recorded = ended(spans)
    assert len(recorded) == 1
    # Not "/widgets/abc123": every widget ID would be its own operation name.
    assert recorded[0].name == "GET /widgets/{id}"


def test_inbound_trace_context_is_continued(
    traced: TestClient, spans: InMemorySpanExporter
) -> None:
    # A caller's trace must continue here rather than a new one starting, or a
    # distributed trace breaks at every service boundary.
    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_span_id = "00f067aa0ba902b7"

    traced.get(
        "/widgets",
        headers={"traceparent": f"00-{trace_id}-{parent_span_id}-01"},
    )

    recorded = ended(spans)
    assert len(recorded) == 1
    assert format(recorded[0].context.trace_id, "032x") == trace_id
    assert recorded[0].parent is not None
    assert format(recorded[0].parent.span_id, "016x") == parent_span_id


def test_service_layer_logs_share_the_request_trace(
    traced: TestClient, spans: InMemorySpanExporter, logs: io.StringIO
) -> None:
    # Anything logged inside the request — not just the access line — must carry
    # the same trace_id, which is the whole point of putting it in a patcher
    # rather than at call sites.
    traced.get("/widgets")

    lines = [json.loads(line) for line in logs.getvalue().strip().splitlines()]
    traced_lines = [line for line in lines if KEY_TRACE_ID in line]
    assert traced_lines, "no log line carried a trace_id"
    assert len({line[KEY_TRACE_ID] for line in traced_lines}) == 1


def test_tracing_can_be_disabled(logs: io.StringIO) -> None:
    from widget_svc.observability import configure_tracing

    config = Config()
    config.observability.tracing.enabled = False
    tracing = configure_tracing(config)

    assert tracing.provider is None
    assert not tracing.exporting
    tracing.shutdown()  # must be safe with no provider


def test_no_collector_means_no_export_but_still_spans() -> None:
    from widget_svc.observability import configure_tracing

    # A fresh `make run` must not emit a single connection-refused retry, but
    # spans still have to exist so logs carry a trace_id.
    config = Config()
    assert config.observability.tracing.otlp_endpoint == ""

    tracing = configure_tracing(config)
    try:
        assert tracing.provider is not None
        assert not tracing.exporting
    finally:
        tracing.shutdown()
