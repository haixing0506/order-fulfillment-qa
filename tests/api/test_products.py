from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import product_by_id, response_data


@pytest.mark.api
@pytest.mark.case("TC-PRD-001")
def test_product_list_requires_authentication(client: TestClient):
    response = client.get("/api/v1/products")
    assert response.status_code == 401


@pytest.mark.api
@pytest.mark.case("TC-PRD-002")
def test_product_list_returns_seeded_catalog(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/products?page_size=100", headers=operator_headers)
    assert response.status_code == 200
    data = response_data(response)
    assert data["pagination"]["total"] == 12
    assert len(data["items"]) == 12
    assert "音频设备" in data["categories"]


@pytest.mark.api
@pytest.mark.case("TC-PRD-003")
def test_product_search_matches_chinese_name(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get(
        "/api/v1/products?search=耳机", headers=operator_headers
    )
    assert response.status_code == 200
    items = response_data(response)["items"]
    assert len(items) == 1
    assert items[0]["sku"] == "SKU-1001"


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-PRD-004")
def test_product_search_treats_sql_metacharacters_as_text(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get(
        "/api/v1/products?search=%27%20OR%201%3D1--",
        headers=operator_headers,
    )
    assert response.status_code == 200
    assert response_data(response)["items"] == []


@pytest.mark.api
@pytest.mark.case("TC-PRD-005")
def test_product_pagination_and_category_filter(
    client: TestClient, operator_headers: dict[str, str]
):
    page = client.get(
        "/api/v1/products?page=2&page_size=5",
        headers=operator_headers,
    )
    assert page.status_code == 200
    assert len(response_data(page)["items"]) == 5

    filtered = client.get(
        "/api/v1/products?category=电脑外设",
        headers=operator_headers,
    )
    assert filtered.status_code == 200
    items = response_data(filtered)["items"]
    assert items
    assert all(item["category"] == "电脑外设" for item in items)


@pytest.mark.api
@pytest.mark.case("TC-PRD-006")
def test_missing_product_returns_structured_404(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/products/99999", headers=operator_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PRODUCT_NOT_FOUND"


@pytest.mark.api
@pytest.mark.case("TC-PRD-007")
def test_admin_can_create_product_and_duplicate_sku_is_rejected(
    client: TestClient, admin_headers: dict[str, str]
):
    payload = {
        "sku": "SKU-9001",
        "name": "测试用扩展电池",
        "category": "配件",
        "price_cents": 12900,
        "stock": 30,
    }
    created = client.post(
        "/api/v1/products", json=payload, headers=admin_headers
    )
    assert created.status_code == 201
    product = response_data(created)
    assert product["sku"] == "SKU-9001"
    assert product["price"] == 129.0

    duplicate = client.post(
        "/api/v1/products", json=payload, headers=admin_headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PRODUCT_SKU_EXISTS"


@pytest.mark.api
@pytest.mark.case("TC-PRD-008")
def test_admin_stock_update_marks_low_stock(
    client: TestClient, admin_headers: dict[str, str]
):
    updated = client.patch(
        "/api/v1/products/1/stock",
        json={"stock": 5},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert response_data(updated)["stock"] == 5
    assert response_data(updated)["low_stock"] is True
    assert product_by_id(client, admin_headers, 1)["low_stock"] is True

