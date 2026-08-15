"""Shared fixtures.

The API fixture builds the app exactly as the composition root does, so the
tests exercise the real middleware chain rather than a bare router.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from widget_svc.api import create_admin, create_api
from widget_svc.api.health import Health
from widget_svc.config import Config
from widget_svc.log import configure
from widget_svc.service import Widgets


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


@pytest.fixture
def widgets() -> Widgets:
    """A Widgets with a fixed clock and predictable IDs.

    Assertions can then name exact values instead of matching patterns.
    """
    counter = {"n": 0}
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def now() -> datetime:
        counter["n"] += 1
        return base + timedelta(seconds=counter["n"])

    def new_id() -> str:
        return f"widget-{counter['n']}"

    return Widgets(now=now, new_id=new_id)


@pytest.fixture
def client(config: Config, widgets: Widgets) -> Iterator[TestClient]:
    with TestClient(create_api(config, widgets)) as test_client:
        yield test_client


@pytest.fixture
def health() -> Health:
    return Health()


@pytest.fixture
def admin_client(config: Config, health: Health) -> Iterator[TestClient]:
    with TestClient(create_admin(config, health), raise_server_exceptions=False) as test_client:
        yield test_client
