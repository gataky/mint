"""The request path: verbs, URL joining, headers, and binding a response."""

from __future__ import annotations

import httpx2
import pytest
from pydantic import BaseModel, TypeAdapter

from conftest import json_response, make_client, problem_response, recording
from mint_client import (
    Client,
    ResponseValidationError,
    UpstreamConflictError,
    UpstreamNotFoundError,
    UpstreamRateLimitedError,
    UpstreamServerError,
    UpstreamUnavailableError,
    __version__,
)


class Widget(BaseModel):
    id: str
    name: str


async def test_get_returns_the_response_when_into_is_omitted() -> None:
    handler, _ = recording(json_response(200, {"id": "w1", "name": "bolt"}))
    async with make_client(handler) as client:
        response = await client.get("/widgets/w1")

    assert isinstance(response, httpx2.Response)
    assert response.json() == {"id": "w1", "name": "bolt"}


async def test_into_binds_a_model() -> None:
    handler, _ = recording(json_response(200, {"id": "w1", "name": "bolt"}))
    async with make_client(handler) as client:
        widget = await client.get("/widgets/w1", into=Widget)

    assert widget == Widget(id="w1", name="bolt")


async def test_into_binds_a_list_of_models() -> None:
    # The collection case is the one a bare `type[T]` would not cover, and the
    # reason `into` accepts a generic alias rather than only a class.
    body = [{"id": "w1", "name": "bolt"}, {"id": "w2", "name": "nut"}]
    handler, _ = recording(json_response(200, body))
    async with make_client(handler) as client:
        widgets = await client.get("/widgets", into=list[Widget])

    assert widgets == [Widget(id="w1", name="bolt"), Widget(id="w2", name="nut")]


async def test_into_accepts_a_prebuilt_type_adapter() -> None:
    handler, _ = recording(json_response(200, {"w1": 3}))
    async with make_client(handler) as client:
        counts = await client.get("/counts", into=TypeAdapter(dict[str, int]))

    assert counts == {"w1": 3}


async def test_type_adapters_are_built_once_per_type() -> None:
    handler, _ = recording(json_response(200, {"id": "w1", "name": "bolt"}))
    async with make_client(handler) as client:
        await client.get("/widgets/w1", into=Widget)
        first = client._adapter(Widget)
        await client.get("/widgets/w1", into=Widget)

        assert client._adapter(Widget) is first


async def test_a_response_that_does_not_fit_raises_validation_error() -> None:
    handler, _ = recording(json_response(200, {"id": "w1"}))  # no name
    async with make_client(handler) as client:
        with pytest.raises(ResponseValidationError) as caught:
            await client.get("/widgets/w1", into=Widget)

    # Not a TransportError and not an UpstreamError: the call succeeded and the
    # peer's contract is what broke.
    assert caught.value.status == 200
    assert caught.value.peer == "widget-svc"
    assert "Widget" in caught.value.message


async def test_post_sends_a_json_body() -> None:
    handler, seen = recording(json_response(201, {"id": "w9", "name": "cog"}))
    async with make_client(handler) as client:
        created = await client.post("/widgets", json={"name": "cog"}, into=Widget)

    assert created.id == "w9"
    assert seen[0].method == "POST"
    assert seen[0].read() == b'{"name":"cog"}'


@pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete"])
async def test_every_verb_reaches_the_transport(verb: str) -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await getattr(client, verb)("/widgets")

    assert seen[0].method == verb.upper()


async def test_head_reaches_the_transport() -> None:
    handler, seen = recording(httpx2.Response(200))
    async with make_client(handler) as client:
        await client.head("/widgets")

    assert seen[0].method == "HEAD"


async def test_base_url_is_joined_with_the_path() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler, base_url="http://widget-svc.test:8080/") as client:
        await client.get("/widgets/w1")

    assert str(seen[0].url) == "http://widget-svc.test:8080/widgets/w1"


async def test_query_parameters_are_sent() -> None:
    handler, seen = recording(json_response(200, []))
    async with make_client(handler) as client:
        await client.get("/widgets", params={"limit": 10})

    assert seen[0].url.params["limit"] == "10"


async def test_user_agent_names_the_service_and_the_library() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler, user_agent="widget-svc/0.1.0") as client:
        await client.get("/widgets")

    assert seen[0].headers["user-agent"] == f"widget-svc/0.1.0 mint-client/{__version__}"


async def test_user_agent_falls_back_to_the_library_alone() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    assert seen[0].headers["user-agent"] == f"mint-client/{__version__}"


async def test_peer_headers_are_sent_on_every_request() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler, headers={"X-Api-Key": "static"}) as client:
        await client.get("/widgets")
        await client.get("/widgets/w1")

    assert all(request.headers["x-api-key"] == "static" for request in seen)


async def test_per_call_headers_are_merged() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler, headers={"X-Api-Key": "static"}) as client:
        await client.get("/widgets", headers={"X-Trace-Hint": "yes"})

    assert seen[0].headers["x-api-key"] == "static"
    assert seen[0].headers["x-trace-hint"] == "yes"


async def test_accept_advertises_json_and_problem_json() -> None:
    handler, seen = recording(json_response(200, {}))
    async with make_client(handler) as client:
        await client.get("/widgets")

    assert seen[0].headers["accept"] == "application/json, application/problem+json"


async def test_redirects_are_not_followed() -> None:
    # A redirect between services is a misconfiguration worth seeing, not a
    # cost worth paying silently on every call forever.
    handler, _ = recording(httpx2.Response(307, headers={"location": "/widgets/w2"}))
    async with make_client(handler) as client:
        response = await client.get("/widgets/w1")

    assert isinstance(response, httpx2.Response)
    assert response.status_code == 307


class TestUpstreamErrors:
    """A 4xx or 5xx becomes a typed exception carrying the peer's own words."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (404, UpstreamNotFoundError),
            (409, UpstreamConflictError),
            (429, UpstreamRateLimitedError),
            (503, UpstreamUnavailableError),
        ],
    )
    async def test_status_selects_the_exception_class(
        self, status: int, expected: type[Exception]
    ) -> None:
        handler, _ = recording(problem_response(status, "nope"))
        async with make_client(handler) as client:
            with pytest.raises(expected):
                await client.get("/widgets/w1")

    async def test_an_unmapped_5xx_is_still_catchable_by_class(self) -> None:
        handler, _ = recording(problem_response(507, "out of space"))
        async with make_client(handler) as client:
            with pytest.raises(UpstreamServerError):
                await client.get("/widgets/w1")

    async def test_the_problem_body_is_parsed_onto_the_exception(self) -> None:
        handler, _ = recording(problem_response(404, 'no widget with id "w1"', title="Not Found"))
        async with make_client(handler) as client:
            with pytest.raises(UpstreamNotFoundError) as caught:
                await client.get("/widgets/w1")

        problem = caught.value.problem
        assert problem is not None
        assert problem.detail == 'no widget with id "w1"'
        assert problem.title == "Not Found"
        assert problem.status == 404

    async def test_a_non_problem_body_leaves_problem_absent(self) -> None:
        # Absent, never an empty Problem: "the upstream told us nothing" and
        # "the upstream does not speak RFC 9457" are different facts.
        handler, _ = recording(httpx2.Response(500, text="<html>oh no</html>"))
        async with make_client(handler) as client:
            with pytest.raises(UpstreamServerError) as caught:
                await client.get("/widgets/w1")

        assert caught.value.problem is None
        assert "<html>" not in str(caught.value)

    async def test_the_upstream_request_id_is_captured(self) -> None:
        response = problem_response(500, "boom")
        response.headers["X-Request-Id"] = "upstream-abc"
        handler, _ = recording(response)
        async with make_client(handler) as client:
            with pytest.raises(UpstreamServerError) as caught:
                await client.get("/widgets/w1")

        assert caught.value.request_id == "upstream-abc"

    async def test_retry_after_seconds_are_parsed(self) -> None:
        response = problem_response(429, "slow down")
        response.headers["Retry-After"] = "30"
        handler, _ = recording(response)
        async with make_client(handler) as client:
            with pytest.raises(UpstreamRateLimitedError) as caught:
                await client.get("/widgets/w1")

        assert caught.value.retry_after == 30.0

    async def test_a_nonsense_retry_after_is_ignored_rather_than_fatal(self) -> None:
        response = problem_response(429, "slow down")
        response.headers["Retry-After"] = "soon-ish"
        handler, _ = recording(response)
        async with make_client(handler) as client:
            with pytest.raises(UpstreamRateLimitedError) as caught:
                await client.get("/widgets/w1")

        assert caught.value.retry_after is None

    async def test_the_message_names_the_target(self) -> None:
        handler, _ = recording(problem_response(404, "gone"))
        async with make_client(handler) as client:
            with pytest.raises(UpstreamNotFoundError) as caught:
                await client.get("/widgets/w1")

        rendered = str(caught.value)
        assert "GET" in rendered
        assert "widget-svc" in rendered
        assert "404" in rendered


class TestTransportErrors:
    """A call that never produced a response."""

    async def test_a_connect_failure_becomes_connect_error(self) -> None:
        from mint_client import ConnectError

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("nope", request=request)

        async with make_client(handler) as client:
            with pytest.raises(ConnectError) as caught:
                await client.get("/widgets")

        assert caught.value.peer == "widget-svc"
        assert isinstance(caught.value.cause, httpx2.ConnectError)

    async def test_a_read_timeout_becomes_deadline_exceeded(self) -> None:
        from mint_client import DeadlineExceededError

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("too slow", request=request)

        async with make_client(handler) as client:
            with pytest.raises(DeadlineExceededError):
                await client.get("/widgets")

    async def test_an_unrelated_exception_is_not_swallowed(self) -> None:
        # A bug in this process must not be reported as an upstream fault.
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise ZeroDivisionError("a real bug")

        async with make_client(handler) as client:
            with pytest.raises(ZeroDivisionError):
                await client.get("/widgets")


async def test_aclose_closes_the_pool() -> None:
    handler, _ = recording(json_response(200, {}))
    client = make_client(handler)
    await client.get("/widgets")
    await client.aclose()

    assert client._http.is_closed


def test_typing_of_into_is_checked_by_mypy() -> None:
    """A placeholder so the annotations below are type-checked.

    ``make lint`` runs mypy over ``tests/`` too, so these assignments are the
    assertion: if the overloads regress, ``into=Widget`` starts returning
    ``Response`` and this file stops type-checking.
    """

    async def _usage(client: Client) -> None:
        widget: Widget = await client.get("/widgets/w1", into=Widget)
        widgets: list[Widget] = await client.get("/widgets", into=list[Widget])
        raw: httpx2.Response = await client.get("/widgets")
        created: Widget = await client.post("/widgets", json={}, into=Widget)
        del widget, widgets, raw, created
