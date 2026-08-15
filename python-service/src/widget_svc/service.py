"""Business logic.

This layer takes and returns plain models: no ``Request``, no FastAPI types, no
driver types. The transport calls into it; it never calls back out.

Widgets are held in memory. A real service would define a repository protocol
here — owned by this module — implement it elsewhere, and have the composition
root inject it.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from widget_svc.errors import ConflictError, InvalidError, NotFoundError

#: Colours a widget may be. A Literal rather than a list, so the OpenAPI enum,
#: the request validation and the type checker all read the same declaration.
Color = Literal["red", "green", "blue"]


class Widget(BaseModel):
    """The example resource, threaded through both layers."""

    id: str = Field(description="Unique widget identifier.")
    name: str = Field(description="Human-readable widget name.")
    color: Color = Field(description="Widget color.")
    created_at: datetime = Field(description="When the widget was created, RFC 3339.")

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        # Millisecond precision with a trailing Z, matching the Go service.
        # Pydantic would otherwise emit microseconds and a "+00:00" offset.
        utc = value.astimezone(UTC)
        return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


class NewWidget(BaseModel):
    """The input to :meth:`Widgets.create`.

    A separate model from :class:`Widget` because the server, not the client,
    owns ``id`` and ``created_at``.
    """

    name: str = Field(min_length=1, max_length=64, description="Human-readable widget name.")
    color: Color = Field(description="Widget color.")


class Widgets:
    """Widget business logic over an in-memory store."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._items: dict[str, Widget] = {}
        self._lock = asyncio.Lock()
        # Injected so tests get deterministic output without touching the clock.
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: secrets.token_hex(8))

    async def list(self) -> list[Widget]:
        """Every widget, oldest first."""
        async with self._lock:
            return sorted(self._items.values(), key=lambda w: (w.created_at, w.id))

    async def get(self, widget_id: str) -> Widget:
        """One widget by ID."""
        async with self._lock:
            widget = self._items.get(widget_id)
        if widget is None:
            raise NotFoundError(f'no widget with id "{widget_id}"')
        return widget

    async def create(self, new: NewWidget) -> Widget:
        """Store a new widget and return it."""
        # Business rules live here, not in the transport. The transport has
        # already checked the shape; this checks the meaning.
        name = new.name.strip()
        if not name:
            raise InvalidError("name must not be blank")

        async with self._lock:
            for existing in self._items.values():
                if existing.name.casefold() == name.casefold():
                    raise ConflictError(f'a widget named "{name}" already exists')

            widget = Widget(
                id=self._new_id(),
                name=name,
                color=new.color,
                created_at=self._now().astimezone(UTC),
            )
            self._items[widget.id] = widget

        return widget
