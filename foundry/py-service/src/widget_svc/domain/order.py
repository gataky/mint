"""The order entity."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from widget_svc.domain.timestamps import rfc3339

#: Bounds how many widgets one order may ask for.
MAX_ORDER_QUANTITY = 1000


class Order(BaseModel):
    """A request for some number of one widget.

    It exists in the template to show a resource that *references* another one:
    creating an order has to consult widgets, which is what makes the dependency
    direction between service modules visible.
    """

    id: str = Field(description="Unique order identifier.")
    widget_id: str = Field(description="The widget being ordered.")
    quantity: int = Field(description="How many widgets were ordered.")
    created_at: datetime = Field(description="When the order was placed, RFC 3339.")

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str:
        return rfc3339(value)


class NewOrder(BaseModel):
    """The input to placing an order."""

    widget_id: str = Field(min_length=1, max_length=64, description="The widget to order.")
    quantity: int = Field(ge=1, le=MAX_ORDER_QUANTITY, description="How many to order.")
