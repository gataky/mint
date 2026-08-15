"""Liveness and readiness."""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from {@ package_name @}.api.health import Check, Health
from {@ package_name @}.api.problem import PROBLEM_CONTENT_TYPE


async def _fails() -> None:
    raise RuntimeError("connection refused")


async def _passes() -> None:
    return None


def test_liveness_ignores_dependencies(admin_client: TestClient, health: Health) -> None:
    # A liveness probe that checks a dependency restarts the service when the
    # dependency is the thing that is broken. It must pass regardless.
    health.register(Check(name="always-fails", probe=_fails, required=True))

    response = admin_client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_with_no_checks_is_ready(admin_client: TestClient) -> None:
    assert admin_client.get("/readyz").status_code == 200


@pytest.mark.parametrize(
    ("required", "expected_status", "expected_body"),
    [
        pytest.param(
            False,
            200,
            "ok",
            id="a failing optional check is reported but stays ready",
        ),
        pytest.param(
            True,
            503,
            "fail",
            id="a failing required check takes the service out of rotation",
        ),
    ],
)
def test_readiness_fails_only_on_required_checks(
    admin_client: TestClient,
    health: Health,
    required: bool,
    expected_status: int,
    expected_body: str,
) -> None:
    health.register(Check(name="database", probe=_fails, required=required))

    response = admin_client.get("/readyz")

    assert response.status_code == expected_status
    body = response.json()
    assert body["status"] == expected_body

    # Whatever the outcome, the body lists every check — that is what makes the
    # endpoint useful for diagnosis rather than just for routing.
    assert len(body["checks"]) == 1
    assert body["checks"][0]["name"] == "database"
    assert body["checks"][0]["error"] == "connection refused"


def test_readiness_reports_every_check(admin_client: TestClient, health: Health) -> None:
    health.register(Check(name="database", probe=_passes, required=True))
    health.register(Check(name="cache", probe=_fails, required=False))

    body = admin_client.get("/readyz").json()

    by_name = {check["name"]: check["status"] for check in body["checks"]}
    assert by_name == {"database": "ok", "cache": "fail"}


def test_readiness_times_out_a_slow_check(admin_client: TestClient, health: Health) -> None:
    async def hangs() -> None:
        await asyncio.sleep(10)

    # A check with no timeout of its own would hang the whole probe.
    health.register(Check(name="slow", probe=hangs, required=True, timeout_seconds=0.02))

    response = admin_client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"][0]["error"].startswith("timed out")


def test_drain_makes_the_service_unready(admin_client: TestClient, health: Health) -> None:
    health.drain()

    response = admin_client.get("/readyz")

    assert response.status_code == 503
    # "draining" is distinguishable from "fail" on purpose: mid-drain the
    # service is healthy, it is just leaving rotation deliberately.
    assert response.json()["status"] == "draining"


def test_liveness_stays_up_while_draining(admin_client: TestClient, health: Health) -> None:
    health.drain()

    # Failing liveness during a drain gets the process killed instead of allowed
    # to finish its in-flight requests.
    assert admin_client.get("/healthz").status_code == 200


def test_admin_rejects_unknown_paths_with_problem_json(admin_client: TestClient) -> None:
    response = admin_client.get("/not-a-thing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
