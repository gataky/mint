"""RFC 3339 timestamp formatting, shared by every entity.

Go's ``encoding/json`` renders a ``time.Time`` as RFC 3339 with the fractional
second trimmed of trailing zeros, and with the fraction omitted entirely when it
is zero::

    0 ns          ->  2026-01-01T00:00:00Z
    10 ms         ->  2026-01-01T00:00:00.01Z
    123 ms        ->  2026-01-01T00:00:00.123Z

Python's default would emit ``.010000`` and a ``+00:00`` offset, so this matches
Go's rule rather than the other way round. Changing the Go side would mean
either a transport DTO layer or making the domain package import huma so a
custom time type could supply its own OpenAPI schema — reflection alone renders
a wrapped ``time.Time`` as ``{"type": "object"}``. Both cost more than this
function does.
"""

from __future__ import annotations

from datetime import UTC, datetime


def rfc3339(value: datetime) -> str:
    """Render a datetime the way the Go service renders one."""
    utc = value.astimezone(UTC)

    # Milliseconds: the precision the API publishes. Anything finer is dropped
    # rather than rounded, matching the service layer's truncation.
    fraction = f"{utc.microsecond // 1000:03d}".rstrip("0")
    suffix = f".{fraction}" if fraction else ""

    return f"{utc:%Y-%m-%dT%H:%M:%S}{suffix}Z"
