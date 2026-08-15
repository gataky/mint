"""Liveness and readiness, served on the admin port."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, Request, Response, status

type Probe = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class Check:
    """One readiness probe.

    A dependency the service needs, with its own timeout and its own opinion
    about whether failing should take the service out of rotation.
    """

    name: str
    probe: Probe
    required: bool = False
    timeout_seconds: float = 2.0


@dataclass(slots=True)
class Health:
    """Owns the liveness and readiness state."""

    checks: list[Check] = field(default_factory=list)
    draining: bool = False

    def register(self, check: Check) -> None:
        """Add a readiness check. Call during startup, before the listeners."""
        self.checks.append(check)

    def drain(self) -> None:
        """Mark the service as shutting down.

        Readiness starts failing immediately so a load balancer stops sending
        new work, while in-flight requests finish.
        """
        self.draining = True

    async def ready(self) -> tuple[dict[str, object], int]:
        """Run every check and report all of them, whatever the outcome.

        Only a failing *required* check makes the service unready — an optional
        dependency being down is worth surfacing, not worth removing the service
        from rotation for.
        """
        if self.draining:
            return {"status": "draining", "checks": []}, status.HTTP_503_SERVICE_UNAVAILABLE

        results = await asyncio.gather(*(_run(check) for check in self.checks))

        failed = any(r["status"] != "ok" and r["required"] for r in results)
        return (
            {"status": "fail" if failed else "ok", "checks": results},
            status.HTTP_503_SERVICE_UNAVAILABLE if failed else status.HTTP_200_OK,
        )


async def _run(check: Check) -> dict[str, object]:
    loop = asyncio.get_running_loop()
    started = loop.time()
    result: dict[str, object] = {"name": check.name, "status": "ok", "required": check.required}

    try:
        async with asyncio.timeout(check.timeout_seconds):
            await check.probe()
    except TimeoutError:
        result["status"] = "fail"
        result["error"] = f"timed out after {check.timeout_seconds:g}s"
    except Exception as exc:
        result["status"] = "fail"
        result["error"] = str(exc)

    result["duration_ms"] = int((loop.time() - started) * 1000)
    return result


def get_health(request: Request) -> Health:
    health: Health = request.app.state.health
    return health


router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness", operation_id="health.live")
async def healthz() -> dict[str, object]:
    """Is the process running?

    This touches no dependency, ever. A liveness probe that checks a database
    restarts the service when the database is the thing that is broken.
    """
    return {"status": "ok", "checks": []}


@router.get("/readyz", summary="Readiness", operation_id="health.ready")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    """Should this instance receive traffic?"""
    body, code = await get_health(request).ready()
    response.status_code = code
    return body
