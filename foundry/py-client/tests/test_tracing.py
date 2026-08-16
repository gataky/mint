"""Trace propagation: the reason this library exists rather than a bare httpx."""

from __future__ import annotations

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from conftest import json_response, make_client, problem_response, recording
from mint_client import UpstreamNotFoundError


async def test_traceparent_is_injected(recorded_spans: InMemorySpanExporter) -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    assert "traceparent" in seen[0].headers


async def test_the_peer_is_parented_to_the_client_span(
    recorded_spans: InMemorySpanExporter,
) -> None:
    """The injected context must name *this attempt*, not its caller.

    Getting this wrong is invisible locally and produces a trace where every
    upstream span hangs off the server span, with the client spans as unrelated
    siblings — so a slow call cannot be attributed to the call that made it.
    """
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    exported = recorded_spans.get_finished_spans()
    assert len(exported) == 1
    client_span = exported[0]

    traceparent = seen[0].headers["traceparent"]
    _, trace_id, span_id, _ = traceparent.split("-")

    assert trace_id == format(client_span.context.trace_id, "032x")
    assert span_id == format(client_span.context.span_id, "016x")


async def test_the_client_span_continues_an_existing_trace(
    recorded_spans: InMemorySpanExporter,
) -> None:
    handler, _ = recording(json_response(200, {}))
    tracer = trace.get_tracer("test")

    with tracer.start_as_current_span("GET /orders") as server_span:
        expected = server_span.get_span_context().trace_id
        async with make_client(handler) as client:
            await client.get("/widgets")

    client_span = next(s for s in recorded_spans.get_finished_spans() if s.kind is SpanKind.CLIENT)
    assert client_span.context.trace_id == expected
    assert client_span.parent is not None


async def test_the_span_is_a_client_span(recorded_spans: InMemorySpanExporter) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    assert recorded_spans.get_finished_spans()[0].kind is SpanKind.CLIENT


async def test_the_span_is_named_for_the_method_alone_by_default(
    recorded_spans: InMemorySpanExporter,
) -> None:
    # No route template was given, and the concrete path must never become a
    # span name — that is unbounded cardinality in a trace backend.
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets/w1")

    assert recorded_spans.get_finished_spans()[0].name == "GET"


async def test_a_route_hint_names_the_span_like_the_server_does(
    recorded_spans: InMemorySpanExporter,
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets/w1", route="/widgets/{id}")

    span = recorded_spans.get_finished_spans()[0]
    assert span.name == "GET /widgets/{id}"
    assert span.attributes is not None
    assert span.attributes["http.route"] == "/widgets/{id}"


async def test_span_attributes_follow_the_http_client_convention(
    recorded_spans: InMemorySpanExporter,
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets/w1")

    attributes = recorded_spans.get_finished_spans()[0].attributes
    assert attributes is not None
    assert attributes["http.request.method"] == "GET"
    assert attributes["server.address"] == "widget-svc.test"
    assert attributes["server.port"] == 8080
    assert attributes["peer.service"] == "widget-svc"
    assert attributes["url.full"] == "http://widget-svc.test:8080/widgets/w1"
    assert attributes["http.response.status_code"] == 200


async def test_credentials_are_redacted_from_the_url_attribute(
    recorded_spans: InMemorySpanExporter,
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, base_url="http://user:secret@widget-svc.test:8080") as client:
        await client.get("/widgets")

    attributes = recorded_spans.get_finished_spans()[0].attributes
    assert attributes is not None
    assert "secret" not in str(attributes["url.full"])
    assert "REDACTED" in str(attributes["url.full"])


async def test_a_4xx_sets_the_span_to_error(recorded_spans: InMemorySpanExporter) -> None:
    """For a CLIENT span, OpenTelemetry counts any 4xx as an error.

    (For a SERVER span only 5xx is — a 404 there is the server working
    correctly. The asymmetry is in the spec, and is easy to get backwards.)
    """
    handler, _ = recording(problem_response(404, "gone"))
    async with make_client(handler) as client:
        with pytest.raises(UpstreamNotFoundError):
            await client.get("/widgets/w1")

    span = recorded_spans.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "404"


async def test_a_transport_failure_records_the_error_type(
    recorded_spans: InMemorySpanExporter,
) -> None:
    # The kind of failure lives here rather than in a metric label, which is the
    # documented v1 trade-off.
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    from mint_client import ConnectError

    async with make_client(handler) as client:
        with pytest.raises(ConnectError):
            await client.get("/widgets")

    span = recorded_spans.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "ConnectError"


async def test_one_span_per_call(recorded_spans: InMemorySpanExporter) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")
        await client.get("/widgets")
        await client.get("/widgets")

    assert len(recorded_spans.get_finished_spans()) == 3
