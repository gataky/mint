"""The three client metrics, and the label discipline that keeps them bounded."""

from __future__ import annotations

import httpx2
import pytest
from prometheus_client import CollectorRegistry

from conftest import json_response, make_client, problem_response, recording
from mint_client import ClientMetrics, DeadlineExceededError, UpstreamNotFoundError, bind_deadline
from mint_client.observability import ERROR_STATUS


def sample(registry: CollectorRegistry, name: str, **labels: str) -> float | None:
    value = registry.get_sample_value(name, labels)
    return None if value is None else float(value)


async def test_a_successful_call_is_counted(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=metrics) as client:
        await client.get("/widgets")

    assert (
        sample(
            registry,
            "http_client_requests_total",
            method="GET",
            peer="widget-svc",
            status="200",
        )
        == 1.0
    )


async def test_the_duration_histogram_observes_the_call(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=metrics) as client:
        await client.get("/widgets")

    assert (
        sample(
            registry,
            "http_client_request_duration_seconds_count",
            method="GET",
            peer="widget-svc",
            status="200",
        )
        == 1.0
    )


async def test_the_in_flight_gauge_returns_to_zero(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=metrics) as client:
        await client.get("/widgets")

    assert sample(registry, "http_client_active_requests", method="GET", peer="widget-svc") == 0.0


async def test_the_in_flight_gauge_returns_to_zero_after_a_failure(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    """Otherwise it climbs by one on every failure and never comes back down.

    The same trap the server-side MetricsMiddleware documents — a gauge that
    only decrements on the happy path reads as a permanent backlog.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    from mint_client import ConnectError

    async with make_client(handler, metrics=metrics) as client:
        with pytest.raises(ConnectError):
            await client.get("/widgets")

    assert sample(registry, "http_client_active_requests", method="GET", peer="widget-svc") == 0.0


async def test_an_upstream_error_is_counted_under_its_status(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    handler, _ = recording(problem_response(404, "gone"))
    async with make_client(handler, metrics=metrics) as client:
        with pytest.raises(UpstreamNotFoundError):
            await client.get("/widgets/w1")

    assert (
        sample(
            registry,
            "http_client_requests_total",
            method="GET",
            peer="widget-svc",
            status="404",
        )
        == 1.0
    )


async def test_a_transport_failure_uses_the_error_sentinel(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    """No response means no status, and inventing one would be worse.

    A synthetic 503 here is indistinguishable in a dashboard from a real 503 the
    peer actually sent.
    """

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    from mint_client import ConnectError

    async with make_client(handler, metrics=metrics) as client:
        with pytest.raises(ConnectError):
            await client.get("/widgets")

    assert (
        sample(
            registry,
            "http_client_requests_total",
            method="GET",
            peer="widget-svc",
            status=ERROR_STATUS,
        )
        == 1.0
    )


async def test_a_call_abandoned_for_lack_of_budget_is_still_counted(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    """A service constantly blowing its deadline must not look idle.

    The budget check is inside the instrumented region for exactly this reason:
    the call never reached a socket, but it is still a failed outbound call.
    """
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=metrics) as client:
        with bind_deadline(-1.0), pytest.raises(DeadlineExceededError):
            await client.get("/widgets")

    assert (
        sample(
            registry,
            "http_client_requests_total",
            method="GET",
            peer="widget-svc",
            status=ERROR_STATUS,
        )
        == 1.0
    )
    assert sample(registry, "http_client_active_requests", method="GET", peer="widget-svc") == 0.0


async def test_the_peer_label_is_the_service_name_not_the_url(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    """One series per peer, never one per URL.

    The outbound version of the server's route-template rule: a concrete path as
    a label is how a dashboard grows a series per widget ID.
    """
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=metrics) as client:
        await client.get("/widgets/w1")
        await client.get("/widgets/w2")
        await client.get("/widgets/w3")

    assert (
        sample(
            registry,
            "http_client_requests_total",
            method="GET",
            peer="widget-svc",
            status="200",
        )
        == 3.0
    )


async def test_one_metrics_object_serves_many_peers(
    registry: CollectorRegistry, metrics: ClientMetrics
) -> None:
    """Sharing is required, not merely allowed: a registry rejects duplicates."""
    handler, _ = recording(json_response(200, {}))

    async with (
        make_client(handler, peer="widget-svc", metrics=metrics) as widgets,
        make_client(handler, peer="parts-svc", metrics=metrics) as parts,
    ):
        await widgets.get("/widgets")
        await parts.get("/parts")

    for peer in ("widget-svc", "parts-svc"):
        assert (
            sample(
                registry,
                "http_client_requests_total",
                method="GET",
                peer=peer,
                status="200",
            )
            == 1.0
        )


async def test_metrics_are_optional() -> None:
    # A client built without them still works; it just records nothing.
    handler, _ = recording(json_response(200, {}))
    async with make_client(handler, metrics=None) as client:
        response = await client.get("/widgets")

    assert response.status_code == 200
