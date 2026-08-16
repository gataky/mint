"""Go-style duration strings, as a pydantic type.

``"15s"``, ``"1m30s"``, ``"500ms"``. A bare number is seconds.

This lives in the client library rather than in a service because both a
service's own config and a peer's timeout are written in the same YAML, by the
same person, and must mean the same thing. There was one implementation of this
before this package existed; there is still one.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

__all__ = ["Duration", "format_duration", "parse_duration"]

_DURATION_PATTERN = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(value: Any) -> Any:
    """Accept Go-style duration strings so every Mint component reads the same YAML.

    Anything unrecognised is passed through untouched, for pydantic to reject
    with its own error message rather than a bespoke one.
    """
    if isinstance(value, str):
        matches = _DURATION_PATTERN.findall(value.strip())
        if matches:
            seconds = sum(float(amount) * _DURATION_UNITS[unit] for amount, unit in matches)
            return timedelta(seconds=seconds)
    if isinstance(value, int | float):
        return timedelta(seconds=value)
    return value


def format_duration(value: timedelta) -> str:
    """Render a duration the way it is written in YAML, not as a raw float.

    Go's ``time.Duration.String()`` renders 60s as ``"1m0s"``, not ``"1m"``.
    Matching it keeps `make config` output comparable between the two services.
    """
    seconds = value.total_seconds()
    if seconds == 0:
        return "0s"
    if seconds < 1:
        return f"{seconds * 1000:g}ms"

    parts = []
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        parts.append(f"{hours:g}h")
    if minutes or parts:
        parts.append(f"{minutes:g}m")
    parts.append(f"{secs:g}s")
    return "".join(parts)


#: A ``timedelta`` that reads Go duration strings and renders back to one.
Duration = Annotated[
    timedelta,
    BeforeValidator(parse_duration),
    PlainSerializer(format_duration, return_type=str),
]
