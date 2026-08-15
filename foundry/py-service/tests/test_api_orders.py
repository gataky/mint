"""The order routes, including the cross-resource behaviour."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from widget_svc.api.problem import PROBLEM_CONTENT_TYPE
from widget_svc.domain import MAX_ORDER_QUANTITY


def seed_widget(client: TestClient, name: str = "sprocket") -> str:
    """Create a widget through the API and return its ID."""
    response = client.post("/widgets", json={"name": name, "color": "red"})
    assert response.status_code == 201, response.text
    widget_id: str = response.json()["id"]
    return widget_id


def test_place_and_fetch_order(client: TestClient) -> None:
    widget_id = seed_widget(client)

    created = client.post("/orders", json={"widget_id": widget_id, "quantity": 3})
    assert created.status_code == 201, created.text

    order = created.json()
    assert order["widget_id"] == widget_id
    assert order["quantity"] == 3

    fetched = client.get(f"/orders/{order['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == order["id"]


def test_order_for_unknown_widget_is_bad_request(client: TestClient) -> None:
    response = client.post("/orders", json={"widget_id": "no-such-widget", "quantity": 1})

    # 400, not 404: the request is well formed and /orders exists — what is
    # wrong is the reference inside the body.
    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert response.json()["title"] == "Bad Request"


@pytest.mark.parametrize(
    "quantity",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(MAX_ORDER_QUANTITY + 1, id="above the maximum"),
    ],
)
def test_order_quantity_is_validated_at_the_edge(client: TestClient, quantity: int) -> None:
    widget_id = seed_widget(client)

    response = client.post("/orders", json={"widget_id": widget_id, "quantity": quantity})

    # The bounds are declared on the model, so FastAPI rejects these before the
    # service is reached.
    assert response.status_code == 422, response.text


def test_list_orders_returns_empty_array(client: TestClient) -> None:
    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json() == []


def test_unknown_order_is_not_found(client: TestClient) -> None:
    response = client.get("/orders/no-such-id")

    assert response.status_code == 404, response.text
    assert response.json()["instance"] == "/orders/no-such-id"


def test_openapi_documents_both_resources(client: TestClient) -> None:
    document = client.get("/openapi.json").json()

    # Adding a resource must show up in the published document without anyone
    # editing it by hand.
    for path, methods in {
        "/widgets": ["get", "post"],
        "/widgets/{id}": ["get"],
        "/orders": ["get", "post"],
        "/orders/{id}": ["get"],
    }.items():
        for method in methods:
            assert method in document["paths"][path], f"missing {method.upper()} {path}"

    operation_ids = {
        operation["operationId"]
        for methods in document["paths"].values()
        for operation in methods.values()
    }
    assert {"widgets.list", "widgets.get", "widgets.create"} <= operation_ids
    assert {"orders.list", "orders.get", "orders.create"} <= operation_ids
