"""The reserved slot for retry, backoff and circuit breaking.

**Nothing in this module retries anything, and the client does not call it.**
This is the same device as the empty auth slot in the service's middleware
chain: naming the position and fixing the interface makes the deferral
mechanical rather than remembered, and stops the eventual implementation from
being wedged in wherever it happens to be convenient.

Why v1 does not retry
---------------------
A retry is only safe when the call is idempotent, and the client cannot tell.
``POST /orders`` is not idempotent; ``POST /search`` usually is; ``PUT`` is
supposed to be and frequently is not. Worse, the failure most worth retrying —
a read timeout — is exactly the one where the peer may already have applied the
write. A client that retried by default would, on a bad day, double-charge
someone. Retries also amplify: an upstream at 50% error rate under a 3-attempt
default receives ~2x its normal load precisely when it is least able to serve
it.

None of that is an argument against retrying. It is an argument that the policy
belongs to whoever knows the semantics, which is the caller.

Where it plugs in
-----------------
:meth:`Client._send_once` exists as a separate method for exactly this reason:
it performs one attempt, with its own span and its own metrics. A retry loop
wraps that call in :meth:`Client._send` and nothing else in the client changes —
in particular, the per-attempt span stays per-attempt, so a retried call reads
in a trace as sibling spans under one parent rather than as one long span that
hides the retries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["NEVER", "Attempt", "RetryPolicy"]


@dataclass(frozen=True, slots=True)
class Attempt:
    """One completed attempt, offered to a policy so it can decide what is next."""

    peer: str
    method: str
    path: str

    #: 1 for the first attempt.
    number: int

    #: Seconds this attempt took.
    elapsed: float

    #: The response status, or ``None`` if no response was received.
    status: int | None

    #: The exception this attempt raised, or ``None`` if it returned.
    error: BaseException | None

    #: Seconds left in the request budget, or ``None`` when unbounded. A policy
    #: must not schedule a delay that outlives this.
    remaining: float | None

    #: The peer's ``Retry-After``, in seconds, when it sent a usable one.
    retry_after: float | None = None


@runtime_checkable
class RetryPolicy(Protocol):
    """Decides whether, and how long after, to try again.

    Returning a delay is the whole interface: a policy that wants to give up
    returns ``None``, and one that wants to retry immediately returns ``0.0``.
    Backoff, jitter, budgets and circuit state are all implementable behind it
    without the client learning about any of them.
    """

    def next_delay(self, attempt: Attempt) -> float | None:
        """Seconds to wait before retrying, or ``None`` to raise."""
        ...


class _Never:
    """The only policy that ships: give up after the first attempt."""

    def next_delay(self, attempt: Attempt) -> float | None:
        del attempt
        return None

    def __repr__(self) -> str:
        return "NEVER"


#: The default, and currently the only, policy.
NEVER: RetryPolicy = _Never()
