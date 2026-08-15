"""The HTTP server metrics."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from prometheus_client.metrics_core import Metric
from starlette.testclient import TestClient

from widget_svc.api import create_admin, create_api
from widget_svc.api.health import Health
from widget_svc.api.route import UNMATCHED_ROUTE
from widget_svc.config import Config
from widget_svc.observability import DURATION_BUCKETS, Metrics
from widget_svc.service import Widgets


@pytest.fixture
def metrics() -> Metrics:
    config = Config()
    config.service.owner = "platform"
    return Metrics(config)


@pytest.fixture
def instrumented(metrics: Metrics, widgets: Widgets) -> Iterator[TestClient]:
    """The API with metrics wired exactly as the composition root does."""
    with TestClient(create_api(Config(), widgets, metrics)) as client:
        yield client


def families(metrics: Metrics) -> dict[str, Metric]:
    return {family.name: family for family in metrics.registry.collect()}


def label_keys(family: Metric) -> list[str]:
    # "le" is a histogram bucket boundary, not a dimension of the series.
    return sorted(key for key in family.samples[0].labels if key != "le")


def label_values(metrics: Metrics, family: str, label: str) -> list[str]:
    found = families(metrics)[family]
    return sorted({sample.labels[label] for sample in found.samples if label in sample.labels})


def test_metrics_record_the_agreed_names_and_labels(
    instrumented: TestClient, metrics: Metrics
) -> None:
    instrumented.get("/widgets")

    collected = families(metrics)

    # The names and label keys are the contract. Anything outside this set is
    # language-specific runtime instrumentation and is not compared.
    want = {
        "http_server_requests": ["method", "route", "status"],
        "http_server_request_duration_seconds": ["method", "route", "status"],
        "http_server_active_requests": ["method"],
    }
    for name, expected in want.items():
        assert name in collected, f"no metric family named {name!r}"
        assert label_keys(collected[name]) == expected


def test_metrics_label_the_route_template_not_the_path(
    instrumented: TestClient, metrics: Metrics
) -> None:
    # Two different widgets must land on one series, or every ID ever requested
    # becomes its own time series.
    instrumented.get("/widgets/abc")
    instrumented.get("/widgets/def")

    assert label_values(metrics, "http_server_requests", "route") == ["/widgets/{id}"]


def test_metrics_bound_cardinality_for_unrouted_requests(
    instrumented: TestClient, metrics: Metrics
) -> None:
    # A flood of requests to random paths must not be able to create a series
    # per path.
    for path in ("/nope-1", "/nope-2", "/nope-3"):
        instrumented.get(path)

    assert label_values(metrics, "http_server_requests", "route") == [UNMATCHED_ROUTE]


def test_metrics_count_by_status(instrumented: TestClient, metrics: Metrics) -> None:
    instrumented.get("/widgets")
    instrumented.get("/widgets/missing")

    assert label_values(metrics, "http_server_requests", "status") == ["200", "404"]


def test_active_requests_returns_to_zero(instrumented: TestClient, metrics: Metrics) -> None:
    instrumented.get("/widgets")

    gauge = families(metrics)["http_server_active_requests"]
    assert [sample.value for sample in gauge.samples] == [0.0]


def test_active_requests_is_decremented_after_an_unhandled_exception(
    metrics: Metrics, widgets: Widgets
) -> None:
    app = create_api(Config(), widgets, metrics)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    # Without a decrement on the exception path the gauge climbs by one on
    # every failure and never comes back down.
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/boom")

    gauge = families(metrics)["http_server_active_requests"]
    assert [sample.value for sample in gauge.samples] == [0.0]


def test_created_series_are_suppressed(instrumented: TestClient, metrics: Metrics) -> None:
    instrumented.get("/widgets")

    # Every counter would otherwise be shadowed by a _created gauge carrying a
    # creation timestamp, which the Go service does not emit.
    rendered = metrics.render().decode()
    assert "_created" not in rendered


def test_target_info_carries_the_owner(instrumented: TestClient, metrics: Metrics) -> None:
    instrumented.get("/widgets")

    collected = families(metrics)
    assert "target" in collected, "no target_info family"

    # service_owner belongs here and NOT on the request metrics: a re-org would
    # otherwise change the identity of every series and break rate() across the
    # boundary.
    assert label_keys(collected["target"]) == [
        "deployment_environment_name",
        "service_name",
        "service_owner",
        "service_version",
    ]
    for name in ("http_server_requests", "http_server_request_duration_seconds"):
        assert "service_owner" not in label_keys(collected[name])


def test_duration_uses_the_advisory_buckets(instrumented: TestClient, metrics: Metrics) -> None:
    instrumented.get("/widgets")

    bounds = [
        sample.labels["le"]
        for sample in families(metrics)["http_server_request_duration_seconds"].samples
        if sample.name.endswith("_bucket")
    ]
    # The trailing +Inf bucket is implicit in the declared boundaries.
    assert bounds[:-1] == [str(float(bucket)) for bucket in DURATION_BUCKETS]
    assert bounds[-1] == "+Inf"


def test_metrics_endpoint_is_served_on_admin(
    instrumented: TestClient, metrics: Metrics, health: Health
) -> None:
    instrumented.get("/widgets")

    with TestClient(create_admin(Config(), health, metrics)) as admin:
        response = admin.get("/metrics")

    assert response.status_code == 200
    for name in (
        "http_server_requests_total",
        "http_server_request_duration_seconds",
        "http_server_active_requests",
        "target_info",
    ):
        assert name in response.text, f"/metrics does not mention {name!r}"


def test_admin_surface_is_not_instrumented(
    instrumented: TestClient, metrics: Metrics, health: Health
) -> None:
    instrumented.get("/widgets")

    with TestClient(create_admin(Config(), health, metrics)) as admin:
        admin.get("/healthz")
        admin.get("/readyz")
        admin.get("/metrics")

    # A readiness probe every second and a scrape every fifteen would be most
    # of the metrics if the admin surface counted itself.
    assert label_values(metrics, "http_server_requests", "route") == ["/widgets"]
