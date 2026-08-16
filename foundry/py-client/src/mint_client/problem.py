"""RFC 9457 ``application/problem+json``, parsed rather than guessed at.

Every Mint service returns errors in this shape — that is the guarantee the
repo root makes — so the client reads it back into a model instead of handing
the caller raw bytes. The parse is deliberately total: a peer that returns
something else, or nothing, yields ``None`` and never raises. A client that
crashes while handling an error response turns a recoverable upstream failure
into an unrecoverable local one.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Problem", "ProblemDetail", "parse_problem"]

#: The RFC 9457 media type. A body is only trusted as a problem when it is
#: labelled with this, or with plain JSON *and* carrying the required members.
PROBLEM_CONTENT_TYPE = "application/problem+json"

JSON_CONTENT_TYPE = "application/json"

#: RFC 9457's default when an error has no documentation URI of its own.
DEFAULT_PROBLEM_TYPE = "about:blank"


class ProblemDetail(BaseModel):
    """One entry in a validation failure's ``errors`` array.

    The shape is Mint's, not the RFC's — 9457 says nothing about per-field
    errors — and matches what ``api/problem.py`` emits on a 422.
    """

    model_config = ConfigDict(extra="allow")

    message: str = ""
    location: str | None = None
    value: Any = None


class Problem(BaseModel):
    """An RFC 9457 problem document.

    ``extra="allow"`` is not laxness: 9457 §3.2 explicitly permits extension
    members, and a client that dropped them would silently discard the only
    machine-readable part of a well-designed error.
    """

    model_config = ConfigDict(extra="allow")

    type: str = DEFAULT_PROBLEM_TYPE
    title: str = ""
    status: int = 0
    detail: str = ""
    instance: str = ""
    errors: list[ProblemDetail] = Field(default_factory=list)

    def __str__(self) -> str:
        """The one-line form that ends up in an exception message."""
        return self.detail or self.title or f"HTTP {self.status}"


def parse_problem(content_type: str, body: bytes) -> Problem | None:
    """Read a problem document out of a response body, or return ``None``.

    Never raises. ``None`` means "this response body is not a problem
    document", which is a normal thing for a non-Mint peer to return and is
    reported to the caller as an absent ``.problem`` rather than as a second
    failure.
    """
    media_type = content_type.split(";")[0].strip().lower()
    if media_type not in (PROBLEM_CONTENT_TYPE, JSON_CONTENT_TYPE):
        return None

    try:
        decoded = json.loads(body)
    except ValueError, UnicodeDecodeError:
        return None

    if not isinstance(decoded, dict):
        return None

    # A peer labelling its errors application/json rather than problem+json is
    # common enough to accommodate, but only when the body actually looks like a
    # problem. Without this check every JSON error body — including a bare
    # {"error": "..."} — would be reported as a fully-populated Problem whose
    # every field happened to be empty, which reads as "the upstream said
    # nothing" rather than "the upstream did not speak RFC 9457".
    if media_type == JSON_CONTENT_TYPE and not _looks_like_problem(decoded):
        return None

    try:
        return Problem.model_validate(decoded)
    except ValueError:
        return None


def _looks_like_problem(decoded: dict[str, Any]) -> bool:
    """Whether an ``application/json`` body carries the RFC 9457 core members."""
    return any(key in decoded for key in ("type", "title", "status", "detail"))
