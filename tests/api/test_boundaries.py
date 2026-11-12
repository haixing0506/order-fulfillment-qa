from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import response_data


def post_order(
    client: TestClient,
    headers: dict[str, str],
    items: list[dict],
    remark: str = "",
):
    return client.post(
        "/api/v1/orders",
        json={"items": items, "remark": remark},
        headers={**headers, "Idempotency-Key": uuid4().hex},
    )


@pytest.mark.api
@pytest.mark.case("TC-BND-001")
def test_order_quantity_upper_boundary_is_accepted(
    client: TestClient, operator_headers: dict[str, str]
):
    response = post_order(
        client, operator_headers, [{"product_id": 1, "quantity": 99}]
    )
    assert response.status_code == 201
    assert response_data(response)["item_count"] == 99


@pytest.mark.api
@pytest.mark.case("TC-BND-002")
def test_order_quantity_above_upper_boundary_is_rejected(
    client: TestClient, operator_headers: dict[str, str]
):
    response = post_order(
        client, operator_headers, [{"product_id": 1, "quantity": 100}]
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.api
@pytest.mark.case("TC-BND-003")
def test_duplicate_lines_are_merged_before_quantity_limit(
    client: TestClient, operator_headers: dict[str, str]
):
    response = post_order(
        client,
        operator_headers,
        [
            {"product_id": 1, "quantity": 50},
            {"product_id": 1, "quantity": 50},
        ],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_ITEM_LIMIT_EXCEEDED"


@pytest.mark.api
@pytest.mark.case("TC-BND-004")
def test_remark_length_boundaries(
    client: TestClient, operator_headers: dict[str, str]
):
    accepted = post_order(
        client,
        operator_headers,
        [{"product_id": 1, "quantity": 1}],
        remark="备" * 200,
    )
    rejected = post_order(
        client,
        operator_headers,
        [{"product_id": 1, "quantity": 1}],
        remark="备" * 201,
    )
    assert accepted.status_code == 201
    assert rejected.status_code == 422


@pytest.mark.api
@pytest.mark.case("TC-BND-005")
def test_pagination_size_and_page_boundaries(
    client: TestClient, operator_headers: dict[str, str]
):
    maximum = client.get(
        "/api/v1/products?page=1&page_size=100", headers=operator_headers
    )
    too_large = client.get(
        "/api/v1/products?page=1&page_size=101", headers=operator_headers
    )
    zero_page = client.get(
        "/api/v1/products?page=0&page_size=10", headers=operator_headers
    )
    assert maximum.status_code == 200
    assert too_large.status_code == 422
    assert zero_page.status_code == 422


@pytest.mark.api
@pytest.mark.case("TC-BND-006")
def test_stock_lower_boundary_marks_low_stock(
    client: TestClient, admin_headers: dict[str, str]
):
    response = client.patch(
        "/api/v1/products/1/stock", json={"stock": 0}, headers=admin_headers
    )
    assert response.status_code == 200
    product = response_data(response)
    assert product["stock"] == 0
    assert product["low_stock"] is True


@pytest.mark.api
@pytest.mark.case("TC-BND-007")
def test_stock_upper_boundary_validation(
    client: TestClient, admin_headers: dict[str, str]
):
    maximum = client.patch(
        "/api/v1/products/1/stock",
        json={"stock": 1_000_000},
        headers=admin_headers,
    )
    above = client.patch(
        "/api/v1/products/1/stock",
        json={"stock": 1_000_001},
        headers=admin_headers,
    )
    assert maximum.status_code == 200
    assert response_data(maximum)["stock"] == 1_000_000
    assert above.status_code == 422


@pytest.mark.api
@pytest.mark.case("TC-BND-008")
def test_product_price_boundaries(
    client: TestClient, admin_headers: dict[str, str]
):
    base = {
        "sku": "SKU-BND-01",
        "name": "边界价格商品",
        "category": "测试",
        "stock": 10,
    }
    zero = client.post(
        "/api/v1/products",
        json={**base, "price_cents": 0},
        headers=admin_headers,
    )
    minimum = client.post(
        "/api/v1/products",
        json={**base, "price_cents": 1},
        headers=admin_headers,
    )
    assert zero.status_code == 422
    assert minimum.status_code == 201
    assert response_data(minimum)["price"] == 0.01
