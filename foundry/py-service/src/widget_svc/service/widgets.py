"""Widget business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from widget_svc.domain import ConflictError, InvalidError, NewWidget, Widget

if TYPE_CHECKING:
    from widget_svc.service import Clock, IdGenerator


class WidgetRepository(Protocol):
    """The persistence this service needs.

    **The Protocol is declared here, not in ``repository/``.** The consumer owns
    the interface: this module says what it needs, and an implementation
    elsewhere satisfies it structurally without either one importing the other.
    That is what lets a test substitute a fake, and what will let a Postgres
    implementation land without touching this file.
    """

    async def list(self) -> list[Widget]: ...

    async def get(self, widget_id: str) -> Widget: ...

    # Returns None rather than raising, unlike the Go equivalent which returns
    # a not-found error. "Absent" is not exceptional here, and Optional is how
    # Python says that.
    async def find_by_name(self, name: str) -> Widget | None: ...

    async def create(self, widget: Widget) -> None: ...


class Widgets:
    """The widget business logic."""

    def __init__(self, repo: WidgetRepository, ids: IdGenerator, now: Clock) -> None:
        self._repo = repo
        self._ids = ids
        self._now = now

    async def list(self) -> list[Widget]:
        """Every widget, oldest first."""
        return await self._repo.list()

    async def get(self, widget_id: str) -> Widget:
        """One widget by ID."""
        return await self._repo.get(widget_id)

    async def create(self, new: NewWidget) -> Widget:
        """Validate and store a new widget."""
        # Business rules live here, not in the transport. The transport has
        # already checked the shape; this checks the meaning.
        name = new.name.strip()
        if not name:
            raise InvalidError("name must not be blank")

        if await self._repo.find_by_name(name) is not None:
            raise ConflictError(f'a widget named "{name}" already exists')

        widget = Widget(
            id=self._ids(),
            name=name,
            color=new.color,
            created_at=self._now(),
        )
        await self._repo.create(widget)
        return widget
