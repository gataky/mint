"""What an outbound call inherits from the request that caused it."""

from __future__ import annotations

import asyncio

import httpx2
import pytest

from conftest import json_response, make_client, recording
from mint_client import DeadlineExceededError, bind_deadline, bind_request_id, context, remaining


async def test_the_correlation_id_is_forwarded() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        with bind_request_id("req-123"):
            await client.get("/widgets")

    assert seen[0].headers["x-request-id"] == "req-123"


async def test_no_correlation_id_sends_no_header() -> None:
    # Never an empty header. An empty X-Request-Id downstream looks like a
    # correlation ID that exists and cannot be found, which is worse than none.
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    assert "x-request-id" not in seen[0].headers


async def test_an_explicit_header_wins_over_the_context() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        with bind_request_id("from-context"):
            await client.get("/widgets", headers={"X-Request-Id": "explicit"})

    assert seen[0].headers["x-request-id"] == "explicit"


async def test_the_correlation_id_is_unbound_after_the_block() -> None:
    with bind_request_id("req-123"):
        assert context.request_id() == "req-123"
    assert context.request_id() == ""


class TestDeadline:
    def test_remaining_is_none_without_a_deadline(self) -> None:
        assert remaining() is None

    def test_remaining_counts_down(self) -> None:
        with bind_deadline(10.0):
            left = remaining()
            assert left is not None
            assert 9.0 < left <= 10.0

    def test_a_nested_block_may_tighten_the_deadline(self) -> None:
        with bind_deadline(10.0), bind_deadline(2.0):
            left = remaining()
            assert left is not None
            assert left <= 2.0

    def test_a_nested_block_may_not_widen_the_deadline(self) -> None:
        """The request budget is a ceiling, not a suggestion.

        Without this, one sub-timeout configured too generously lets a handler
        outlive the deadline its own server is enforcing, and the client sees a
        504 with nothing to say which upstream caused it.
        """
        with bind_deadline(2.0), bind_deadline(60.0):
            left = remaining()
            assert left is not None
            assert left <= 2.0

    async def test_a_call_takes_what_is_left_rather_than_a_fresh_allowance(self) -> None:
        async def slow(request: httpx2.Request) -> httpx2.Response:
            # Long enough that only the *inherited* budget can cut it off; the
            # client's own 5s total would let it through.
            await asyncio.sleep(1.0)
            return httpx2.Response(200, json={})

        async with make_client(slow) as client:
            with bind_deadline(0.05):
                with pytest.raises(DeadlineExceededError):
                    await client.get("/widgets")

    async def test_an_exhausted_budget_fails_without_dialling(self) -> None:
        handler, seen = recording(json_response(200, {}))

        async with make_client(handler) as client:
            with bind_deadline(-1.0):
                with pytest.raises(DeadlineExceededError) as caught:
                    await client.get("/widgets")

        assert seen == []  # no connection was opened
        assert "budget exhausted" in caught.value.message

    async def test_a_per_call_override_can_tighten(self) -> None:
        async def slow(request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(1.0)
            return httpx2.Response(200, json={})

        async with make_client(slow) as client:
            with pytest.raises(DeadlineExceededError):
                await client.get("/widgets", timeout_seconds=0.05)

    async def test_a_per_call_override_cannot_escape_the_request_budget(self) -> None:
        async def slow(request: httpx2.Request) -> httpx2.Response:
            await asyncio.sleep(1.0)
            return httpx2.Response(200, json={})

        async with make_client(slow) as client:
            with bind_deadline(0.05):
                # Asks for a minute; gets 50ms, because that is all there is.
                with pytest.raises(DeadlineExceededError):
                    await client.get("/widgets", timeout_seconds=60.0)


async def test_cancellation_is_passed_through_untouched() -> None:
    """A CancelledError means the caller is being torn down.

    Converting it into an ordinary exception is how a task refuses to die and a
    graceful shutdown turns into a hard kill.
    """

    async def cancelled(request: httpx2.Request) -> httpx2.Response:
        raise asyncio.CancelledError

    async with make_client(cancelled) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get("/widgets")
