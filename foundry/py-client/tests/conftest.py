"""Shared fixtures.

Every test runs against ``httpx2.MockTransport``, which is the real client — the
real headers, the real timeout handling, the real error translation — with the
socket replaced. Nothing here binds a port, so the suite is deterministic and
runs offline.
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry

from mint_client import Client, ClientMetrics, ClientsConfig

#: MockTransport accepts a sync handler or an async one, as two distinct
#: callable types — not one callable returning a union. Tests that need to sleep
#: (the deadline ones) need the async form.
SyncHandler = Callable[[httpx2.Request], httpx2.Response]
AsyncHandler = Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]
Handler = SyncHandler | AsyncHandler

#: Every request the client sent, in order, for assertions about headers.
type Recorder = list[httpx2.Request]


@pytest.fixture(scope="session")
def spans() -> InMemorySpanExporter:
    """A real tracer provider, installed once for the whole session.

    ``trace.set_tracer_provider`` takes effect once per process; a second call
    is ignored with a warning. Session scope makes that a property of the
    fixture rather than something each test has to remember.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    # Simple, not Batch: a test that has to flush a queue to see its own span
    # is a test that will be flaky.
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def recorded_spans(spans: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    """The session exporter, emptied before each test that looks at it."""
    spans.clear()
    yield spans
    spans.clear()


@pytest.fixture
def registry() -> CollectorRegistry:
    """A fresh registry per test, so metric values start at zero."""
    return CollectorRegistry()


@pytest.fixture
def metrics(registry: CollectorRegistry) -> ClientMetrics:
    return ClientMetrics(registry)


def json_response(status: int, body: Any, **headers: str) -> httpx2.Response:
    """A JSON response, the way a Mint service would send it."""
    return httpx2.Response(status, json=body, headers=headers)


def problem_response(status: int, detail: str, **extra: Any) -> httpx2.Response:
    """An RFC 9457 response, byte-identical in shape to api/problem.py's."""
    body = {
        "type": "about:blank",
        "title": extra.pop("title", "Error"),
        "status": status,
        "detail": detail,
        "instance": extra.pop("instance", "/widgets/abc"),
        **extra,
    }
    return httpx2.Response(
        status,
        content=jsonlib.dumps(body).encode(),
        headers={"content-type": "application/problem+json"},
    )


def make_client(
    handler: Handler,
    *,
    peer: str = "widget-svc",
    base_url: str = "http://widget-svc.test:8080",
    metrics: ClientMetrics | None = None,
    **kwargs: Any,
) -> Client:
    """A client whose transport is the given handler."""
    return Client(
        peer=peer,
        base_url=base_url,
        metrics=metrics,
        transport=httpx2.MockTransport(handler),
        **kwargs,
    )


def recording(response: httpx2.Response | SyncHandler) -> tuple[SyncHandler, Recorder]:
    """A handler that records every request it is given.

    Pass a Response to answer everything with it, or a handler for anything
    conditional.
    """
    seen: Recorder = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if callable(response):
            return response(request)
        return response

    return handler, seen


@pytest.fixture
def clients_config() -> ClientsConfig:
    """A registry with two peers, one of which overrides the shared defaults."""
    return ClientsConfig.model_validate(
        {
            "timeout": {"total": "5s", "connect": "2s"},
            "user_agent": "widget-svc/0.1.0",
            "peers": {
                "parts_svc": {"base_url": "http://parts-svc.test:8080"},
                "slow_svc": {
                    "base_url": "http://slow-svc.test:8080",
                    "timeout": {"total": "30s"},
                    "headers": {"X-Api-Key": "static"},
                },
            },
        }
    )
