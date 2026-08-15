"""Business logic.

This layer takes and returns domain models: no ``Request``, no FastAPI types, no
driver types. The transport calls into it; it never calls back out.

One module per resource. Each declares the repository ``Protocol`` it needs —
the consumer owns the interface — and the composition root injects an
implementation.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
{% if include_examples %}
from {@ package_name @}.service.orders import OrderRepository, Orders, WidgetLookup
from {@ package_name @}.service.widgets import WidgetRepository, Widgets
{% endif %}
__all__ = [
    "Clock",
    "IdGenerator",
{% if include_examples %}    "OrderRepository",
    "Orders",
    "WidgetLookup",
    "WidgetRepository",
    "Widgets",
{% endif %}    "random_id",
    "system_clock",
]

#: Returns the current time. Injected so tests get deterministic output without
#: touching the machine clock.
type Clock = Callable[[], datetime]

#: Returns a new unique identifier.
type IdGenerator = Callable[[], str]


def system_clock() -> datetime:
    """The real clock, in UTC."""
    return datetime.now(UTC)


def random_id() -> str:
    """A 16-character hex identifier."""
    return secrets.token_hex(8)
