from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import response_data


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-RBAC-001")
def test_viewer_cannot_create_order(
    client: TestClient,
    viewer_headers: dict[str, str],
    order_payload: dict,
):
    response = client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={**viewer_headers, "Idempotency-Key": "viewer-denied"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RBAC_FORBIDDEN"


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-RBAC-002")
def test_operator_cannot_manage_catalog(
    client: TestClient, operator_headers: dict[str, str]
):
    create_product = client.post(
        "/api/v1/products",
        json={
            "sku": "SKU-DENIED",
            "name": "无权限商品",
            "category": "测试",
            "price_cents": 100,
            "stock": 1,
        },
        headers=operator_headers,
    )
    update_stock = client.patch(
        "/api/v1/products/1/stock",
        json={"stock": 999},
        headers=operator_headers,
    )
    assert create_product.status_code == 403
    assert update_stock.status_code == 403


@pytest.mark.api
@pytest.mark.case("TC-RBAC-003")
def test_viewer_can_read_orders(
    client: TestClient, viewer_headers: dict[str, str]
):
    response = client.get("/api/v1/orders", headers=viewer_headers)
    assert response.status_code == 200
    assert response_data(response)["items"]


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-RBAC-004")
def test_viewer_cannot_change_order_status(
    client: TestClient,
    viewer_headers: dict[str, str],
    operator_headers: dict[str, str],
):
    created = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": 1, "quantity": 1}], "remark": ""},
        headers={**operator_headers, "Idempotency-Key": "rbac-status-order"},
    )
    order_id = response_data(created)["id"]
    response = client.patch(
        f"/api/v1/orders/{order_id}/status",
        json={"status": "PICKING"},
        headers=viewer_headers,
    )
    assert response.status_code == 403


@pytest.mark.api
@pytest.mark.case("TC-RBAC-005")
def test_admin_can_cancel_order(
    client: TestClient,
    admin_headers: dict[str, str],
    order_payload: dict,
):
    created = client.post(
        "/api/v1/orders",
        json=order_payload,
        headers={**admin_headers, "Idempotency-Key": "admin-cancel-order"},
    )
    order_id = response_data(created)["id"]
    cancelled = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers=admin_headers
    )
    assert cancelled.status_code == 200
    assert response_data(cancelled)["status"] == "CANCELLED"

