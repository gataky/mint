"""Shared fixtures.

The API fixture builds the app exactly as the composition root does, so the
tests exercise the real middleware chain rather than a bare router.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from widget_svc.api import create_admin, create_api
from widget_svc.api.health import Health
from widget_svc.config import Config
from widget_svc.log import configure
from widget_svc.repository import memory
from widget_svc.service import Orders, Widgets


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def logs() -> Iterator[io.StringIO]:
    """Capture the JSON log tier for assertions about field names."""
    stream = io.StringIO()
    configure(
        level="debug",
        fmt="json",
        service="widget-svc",
        service_version="0.1.0",
        env="local",
        stream=stream,
    )
    yield stream
    configure(fmt="console")


def fixed_clock() -> Callable[[], datetime]:
    """A clock that advances one second per call.

    Ordering assertions can then name exact positions without sleeping.
    """
    counter = {"n": 0}
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def now() -> datetime:
        counter["n"] += 1
        return base + timedelta(seconds=counter["n"])

    return now


def counting_ids(prefix: str) -> Callable[[], str]:
    """Predictable identifiers."""
    counter = {"n": 0}

    def next_id() -> str:
        counter["n"] += 1
        return f"{prefix}-{counter['n']}"

    return next_id


@pytest.fixture
def widgets() -> Widgets:
    """The widget service over an empty in-memory store.

    The service tests use the real repository rather than a bespoke mock. There
    is only one implementation, so the thing exercised is the thing that runs.
    """
    return Widgets(memory.Widgets(), counting_ids("widget"), fixed_clock())


@pytest.fixture
def orders(widgets: Widgets) -> Orders:
    """The order service, sharing the widget service it must consult."""
    return Orders(memory.Orders(), widgets, counting_ids("order"), fixed_clock())


@pytest.fixture
def client(config: Config, widgets: Widgets, orders: Orders) -> Iterator[TestClient]:
    with TestClient(create_api(config, widgets, orders)) as test_client:
        yield test_client


@pytest.fixture
def health() -> Health:
    return Health()


@pytest.fixture
def admin_client(config: Config, health: Health) -> Iterator[TestClient]:
    with TestClient(create_admin(config, health), raise_server_exceptions=False) as test_client:
        yield test_client
