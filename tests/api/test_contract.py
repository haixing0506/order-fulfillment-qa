from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import response_data


@pytest.mark.api
@pytest.mark.case("TC-SYS-001")
def test_health_live_and_ready(client: TestClient):
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 200
    assert response_data(live)["status"] == "UP"
    assert response_data(ready)["database"] == "UP"


@pytest.mark.api
@pytest.mark.case("TC-SYS-002")
def test_success_envelope_contract(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/system/info", headers=operator_headers)
    payload = response.json()
    assert set(payload) == {
        "success",
        "data",
        "meta",
        "request_id",
        "timestamp",
    }
    assert payload["success"] is True
    assert payload["data"]["service"] == "order-fulfillment"


@pytest.mark.api
@pytest.mark.case("TC-SYS-003")
def test_error_envelope_contract(client: TestClient):
    response = client.get("/api/v1/products/99999")
    payload = response.json()
    assert set(payload) == {
        "success",
        "error",
        "request_id",
        "timestamp",
    }
    assert payload["success"] is False
    assert set(payload["error"]) == {"code", "message", "details"}


@pytest.mark.api
@pytest.mark.case("TC-SYS-004")
def test_dashboard_summary_contract(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/dashboard/summary", headers=operator_headers)
    assert response.status_code == 200
    data = response_data(response)
    assert data["product_count"] == 12
    assert data["low_stock_count"] >= 2
    assert 0 <= data["fulfillment_rate"] <= 100
    assert len(data["latest_orders"]) <= 6

