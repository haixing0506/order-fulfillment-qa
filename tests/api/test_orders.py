from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import product_by_id, response_data


def create_order(
    client: TestClient,
    headers: dict[str, str],
    payload: dict,
    idempotency_key: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/orders",
        json=payload,
        headers={
            **headers,
            "Idempotency-Key": idempotency_key or uuid4().hex,
        },
    )
    assert response.status_code == 201, response.text
    return response_data(response)


@pytest.mark.api
@pytest.mark.case("TC-ORD-001")
def test_create_order_calculates_server_side_total_and_deducts_stock(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    before_product_1 = product_by_id(client, operator_headers, 1)
    before_product_4 = product_by_id(client, operator_headers, 4)
    order = create_order(client, operator_headers, order_payload)

    assert order["status"] == "CREATED"
    assert order["total"] == 1397.0
    assert order["item_count"] == 3
    assert len(order["items"]) == 2
    assert product_by_id(client, operator_headers, 1)["stock"] == (
        before_product_1["stock"] - 2
    )
    assert product_by_id(client, operator_headers, 4)["stock"] == (
        before_product_4["stock"] - 1
    )


@pytest.mark.api
@pytest.mark.case("TC-ORD-002")
def test_idempotency_key_replay_returns_same_order(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    key = "fixed-idempotency-key-001"
    first = client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={**operator_headers, "Idempotency-Key": key},
    )
    before = product_by_id(client, operator_headers, 1)["stock"]
    second = client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={**operator_headers, "Idempotency-Key": key},
    )
    after = product_by_id(client, operator_headers, 1)["stock"]
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["meta"]["idempotent_replay"] is True
    assert response_data(first)["id"] == response_data(second)["id"]
    assert before == after


@pytest.mark.api
@pytest.mark.case("TC-ORD-003")
def test_same_idempotency_key_with_different_payload_is_rejected(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    key = "fixed-idempotency-key-002"
    first = client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={**operator_headers, "Idempotency-Key": key},
    )
    assert first.status_code == 201
    changed = {
        "items": [{"product_id": 1, "quantity": 3}],
        "remark": order_payload["remark"],
    }
    second = client.post(
        "/api/v1/orders",
        json=changed,
        headers={**operator_headers, "Idempotency-Key": key},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ORDER_IDEMPOTENCY_CONFLICT"


@pytest.mark.api
@pytest.mark.case("TC-ORD-004")
def test_insufficient_stock_returns_conflict(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": 8, "quantity": 99}], "remark": ""},
        headers={**operator_headers, "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_STOCK_INSUFFICIENT"


@pytest.mark.api
@pytest.mark.case("TC-ORD-005")
def test_invalid_item_quantity_is_rejected(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": 1, "quantity": 0}], "remark": ""},
        headers={**operator_headers, "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.api
@pytest.mark.case("TC-ORD-006")
def test_unknown_product_in_order_returns_404(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": 9999, "quantity": 1}], "remark": ""},
        headers={**operator_headers, "Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.api
@pytest.mark.case("TC-ORD-007")
def test_cancel_order_restores_stock_once(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    order = create_order(client, operator_headers, order_payload)
    after_create = product_by_id(client, operator_headers, 1)["stock"]
    cancelled = client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=operator_headers
    )
    assert cancelled.status_code == 200
    assert response_data(cancelled)["status"] == "CANCELLED"
    after_cancel = product_by_id(client, operator_headers, 1)["stock"]
    assert after_cancel == after_create + 2

    cancelled_again = client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=operator_headers
    )
    assert cancelled_again.status_code == 200
    assert product_by_id(client, operator_headers, 1)["stock"] == after_cancel


@pytest.mark.api
@pytest.mark.case("TC-ORD-008")
def test_valid_status_transition_chain(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    order = create_order(client, operator_headers, order_payload)
    for next_status in ("PICKING", "SHIPPED", "COMPLETED"):
        response = client.patch(
            f"/api/v1/orders/{order['id']}/status",
            json={"status": next_status},
            headers=operator_headers,
        )
        assert response.status_code == 200
        assert response_data(response)["status"] == next_status


@pytest.mark.api
@pytest.mark.case("TC-ORD-009")
def test_skipping_status_is_rejected(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    order = create_order(client, operator_headers, order_payload)
    response = client.patch(
        f"/api/v1/orders/{order['id']}/status",
        json={"status": "COMPLETED"},
        headers=operator_headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_INVALID_TRANSITION"


@pytest.mark.api
@pytest.mark.case("TC-ORD-010")
def test_shipped_order_cannot_be_cancelled(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    order = create_order(client, operator_headers, order_payload)
    for status in ("PICKING", "SHIPPED"):
        response = client.patch(
            f"/api/v1/orders/{order['id']}/status",
            json={"status": status},
            headers=operator_headers,
        )
        assert response.status_code == 200
    cancelled = client.post(
        f"/api/v1/orders/{order['id']}/cancel", headers=operator_headers
    )
    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "ORDER_CANNOT_CANCEL"


@pytest.mark.api
@pytest.mark.case("TC-ORD-011")
def test_order_list_supports_status_filter(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    created = create_order(client, operator_headers, order_payload)
    response = client.get("/api/v1/orders?status=CREATED", headers=operator_headers)
    assert response.status_code == 200
    items = response_data(response)["items"]
    assert all(item["status"] == "CREATED" for item in items)
    assert any(item["id"] == created["id"] for item in items)


@pytest.mark.api
@pytest.mark.case("TC-ORD-012")
def test_order_detail_and_404(
    client: TestClient,
    operator_headers: dict[str, str],
    order_payload: dict,
):
    created = create_order(client, operator_headers, order_payload)
    detail = client.get(f"/api/v1/orders/{created['id']}", headers=operator_headers)
    assert detail.status_code == 200
    assert len(response_data(detail)["items"]) == 2
    missing = client.get("/api/v1/orders/99999", headers=operator_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ORDER_NOT_FOUND"


@pytest.mark.api
@pytest.mark.case("TC-ORD-013")
def test_idempotency_keys_are_scoped_by_user(
    client: TestClient,
    admin_headers: dict[str, str],
    operator_headers: dict[str, str],
):
    key = "shared-key-between-users"
    payload = {"items": [{"product_id": 1, "quantity": 1}], "remark": ""}
    admin_order = client.post(
        "/api/v1/orders",
        json=payload,
        headers={**admin_headers, "Idempotency-Key": key},
    )
    operator_order = client.post(
        "/api/v1/orders",
        json=payload,
        headers={**operator_headers, "Idempotency-Key": key},
    )
    assert admin_order.status_code == 201
    assert operator_order.status_code == 201
    assert response_data(admin_order)["id"] != response_data(operator_order)["id"]


@pytest.mark.api
@pytest.mark.concurrency
@pytest.mark.case("TC-INV-001")
def test_concurrent_orders_do_not_oversell(
    client: TestClient,
    admin_headers: dict[str, str],
    operator_headers: dict[str, str],
):
    product_response = client.post(
        "/api/v1/products",
        json={
            "sku": "SKU-CONC-01",
            "name": "并发测试商品",
            "category": "测试",
            "price_cents": 1000,
            "stock": 5,
        },
        headers=admin_headers,
    )
    assert product_response.status_code == 201
    product_id = response_data(product_response)["id"]

    def place_order(index: int) -> int:
        response = client.post(
            "/api/v1/orders",
            json={
                "items": [{"product_id": product_id, "quantity": 1}],
                "remark": f"concurrency-{index}",
            },
            headers={
                **operator_headers,
                "Idempotency-Key": f"concurrent-key-{index}",
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(place_order, range(10)))

    assert statuses.count(201) == 5
    assert statuses.count(409) == 5
    assert product_by_id(client, admin_headers, product_id)["stock"] == 0

