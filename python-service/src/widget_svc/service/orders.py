"""Order business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from widget_svc.domain import (
    MAX_ORDER_QUANTITY,
    InvalidError,
    NewOrder,
    NotFoundError,
    Order,
    Widget,
)

if TYPE_CHECKING:
    from widget_svc.service import Clock, IdGenerator


class OrderRepository(Protocol):
    """The persistence this service needs."""

    async def list(self) -> list[Order]: ...

    async def get(self, order_id: str) -> Order: ...

    async def create(self, order: Order) -> None: ...


class WidgetLookup(Protocol):
    """The part of the widget service that orders depend on.

    **It is deliberately narrower than :class:`~widget_svc.service.Widgets`.**
    Depending on the whole widget service would make every change to widgets a
    potential change to orders; this says exactly what orders need, and
    ``Widgets`` satisfies it structurally without knowing that orders exist.
    This is the pattern to copy when one resource needs another.
    """

    async def get(self, widget_id: str) -> Widget: ...


class Orders:
    """The order business logic."""

    def __init__(
        self,
        repo: OrderRepository,
        widgets: WidgetLookup,
        ids: IdGenerator,
        now: Clock,
    ) -> None:
        self._repo = repo
        self._widgets = widgets
        self._ids = ids
        self._now = now

    async def list(self) -> list[Order]:
        """Every order, oldest first."""
        return await self._repo.list()

    async def get(self, order_id: str) -> Order:
        """One order by ID."""
        return await self._repo.get(order_id)

    async def create(self, new: NewOrder) -> Order:
        """Validate and store a new order."""
        if not 1 <= new.quantity <= MAX_ORDER_QUANTITY:
            raise InvalidError(f"quantity must be between 1 and {MAX_ORDER_QUANTITY}")

        # The referenced widget has to exist. This is reported as invalid rather
        # than not-found: the request is well formed and /orders exists — what
        # is wrong is the reference inside the body.
        try:
            await self._widgets.get(new.widget_id)
        except NotFoundError as exc:
            raise InvalidError(f'no widget with id "{new.widget_id}"') from exc

        order = Order(
            id=self._ids(),
            widget_id=new.widget_id,
            quantity=new.quantity,
            created_at=self._now(),
        )
        await self._repo.create(order)
        return order
