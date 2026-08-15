"""Entities and the error taxonomy.

This is the innermost layer: it imports nothing from the rest of the service,
and everything else imports it.

One module per resource. Adding a resource means adding a module here, one in
``service/``, one in ``repository/memory/``, and one in ``api/``.

The entities are pydantic models carrying the field constraints FastAPI uses to
build the OpenAPI schema, so one type serves as both the domain model and the
wire format. That is deliberate for a service starting out: a second set of
transport DTOs is real work and buys nothing until the two shapes actually need
to differ. When they do — an internal field that must not be published, or a
wire format that must stay stable across a rename — introduce DTOs in ``api/``
and map to them there, rather than distorting the entity to serve both.
"""

from {@ package_name @}.domain.errors import (
    Category,
    ConflictError,
    ForbiddenError,
    InternalError,
    InvalidError,
    NotFoundError,
    ServiceError,
    UnauthorizedError,
)
{% if include_examples %}from {@ package_name @}.domain.order import MAX_ORDER_QUANTITY, NewOrder, Order
from {@ package_name @}.domain.widget import Color, NewWidget, Widget
{% endif %}
__all__ = [
{% if include_examples %}    "MAX_ORDER_QUANTITY",
{% endif %}    "Category",
{% if include_examples %}    "Color",
{% endif %}    "ConflictError",
    "ForbiddenError",
    "InternalError",
    "InvalidError",
{% if include_examples %}    "NewOrder",
    "NewWidget",
{% endif %}    "NotFoundError",
{% if include_examples %}    "Order",
{% endif %}    "ServiceError",
    "UnauthorizedError",
{% if include_examples %}    "Widget",
{% endif %}]
