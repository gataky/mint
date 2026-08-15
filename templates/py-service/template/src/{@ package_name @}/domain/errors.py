"""The domain error taxonomy.

The service layer raises these. The transport owns the mapping from category to
HTTP status; nothing in this module or in :mod:`{@ package_name @}.service` names a
status code.
"""

from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    """The categories a domain error can have."""

    INVALID = "invalid"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    INTERNAL = "internal"


class ServiceError(Exception):
    """A domain error: a category and a message that is safe to show a client.

    Anything raised that is *not* a ServiceError is an internal error. The
    transport turns those into a 500 with a generic message and logs the detail,
    so an unexpected failure can never be reported as a client mistake.
    """

    category: Category = Category.INTERNAL

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


class InvalidError(ServiceError):
    """A well-formed request that violates a business rule."""

    category = Category.INVALID


class NotFoundError(ServiceError):
    """A resource that does not exist."""

    category = Category.NOT_FOUND


class ConflictError(ServiceError):
    """A request that collides with existing state."""

    category = Category.CONFLICT


class UnauthorizedError(ServiceError):
    """A request with no usable credentials."""

    category = Category.UNAUTHORIZED


class ForbiddenError(ServiceError):
    """A request whose credentials do not permit the action."""

    category = Category.FORBIDDEN


class InternalError(ServiceError):
    """An unexpected failure. The cause is logged and never serialized."""

    category = Category.INTERNAL
