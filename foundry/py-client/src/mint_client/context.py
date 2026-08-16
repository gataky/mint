"""The two things an outbound call inherits from the inbound request.

Both ride on ``ContextVar`` — the same mechanism ``logger.contextualize`` and
OpenTelemetry's own context use — so nothing has to be threaded through call
signatures. A service handler three layers deep can make a call that carries the
right correlation ID and the right deadline without either being an argument to
anything.

**Correlation ID.** ``RequestContextMiddleware`` already reuses an inbound
``X-Request-Id`` so a caller's ID survives one hop. Binding it here is what makes
it survive *every* hop: a single ID spans the whole fan-out, and one grep finds
all of it.

**Deadline.** The server gives each request a ``request_timeout`` budget. An
outbound call that opens its own independent 5s timeout inside a 10s request can
overrun it, and three sequential calls certainly will — the handler is killed
mid-flight and the client sees a 504 with no indication which upstream was slow.
Recording the deadline once, at the point that owns the budget, lets every call
below it take *what is left* rather than a fresh allowance.

The deadline is monotonic, not wall-clock: an NTP step during a request must not
extend or collapse a timeout.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = [
    "bind_deadline",
    "bind_request_id",
    "deadline_at",
    "remaining",
    "request_id",
]

_request_id: ContextVar[str] = ContextVar("mint_client_request_id", default="")

#: An absolute ``time.monotonic()`` value, not a duration.
_deadline: ContextVar[float | None] = ContextVar("mint_client_deadline", default=None)


def request_id() -> str:
    """The correlation ID for the request being served, or ``""``."""
    return _request_id.get()


@contextmanager
def bind_request_id(value: str) -> Iterator[None]:
    """Bind the correlation ID for the duration of the block."""
    token = _request_id.set(value)
    try:
        yield
    finally:
        _request_id.reset(token)


def deadline_at() -> float | None:
    """The absolute monotonic deadline, or ``None`` when the request is unbounded."""
    return _deadline.get()


@contextmanager
def bind_deadline(seconds: float) -> Iterator[None]:
    """Bind a deadline ``seconds`` from now, for the duration of the block.

    A nested call never *widens* an existing deadline. An inner block asking for
    more time than the request has left keeps the tighter of the two, so a
    single misconfigured sub-timeout cannot escape the request budget.
    """
    proposed = time.monotonic() + seconds
    current = _deadline.get()
    token = _deadline.set(proposed if current is None else min(current, proposed))
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining() -> float | None:
    """Seconds left in the request budget, or ``None`` if there is no deadline.

    May be zero or negative, which the client treats as "do not dial": see
    :class:`~mint_client.errors.DeadlineExceededError`.
    """
    at = _deadline.get()
    if at is None:
        return None
    return at - time.monotonic()
