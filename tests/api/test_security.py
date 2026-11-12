from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import response_data


@pytest.mark.security
@pytest.mark.case("TC-SEC-001")
def test_security_headers_are_present(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/products", headers=operator_headers)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


@pytest.mark.api
@pytest.mark.case("TC-SEC-002")
def test_request_id_is_propagated(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get(
        "/api/v1/products",
        headers={**operator_headers, "X-Request-ID": "trace-fixture-0001"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-fixture-0001"
    assert response.json()["request_id"] == "trace-fixture-0001"
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-SEC-003")
def test_password_hash_is_never_exposed(
    client: TestClient, admin_headers: dict[str, str]
):
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    body = response.text.lower()
    assert "password" not in body
    assert "pbkdf2" not in body
    assert "access_token" not in body


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-SEC-004")
def test_unknown_field_in_order_is_rejected(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": 1, "quantity": 1, "price": 0.01}],
            "remark": "",
        },
        headers={**operator_headers, "Idempotency-Key": "mass-assignment"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.api
@pytest.mark.case("TC-SEC-005")
def test_malformed_json_returns_controlled_error(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        content=b'{"items": [',
        headers={**operator_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Traceback" not in response.text


@pytest.mark.api
@pytest.mark.case("TC-SEC-006")
def test_unknown_route_uses_structured_error(
    client: TestClient, operator_headers: dict[str, str]
):
    response = client.get("/api/v1/unknown-route", headers=operator_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert response.json()["request_id"]


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-SEC-007")
def test_viewer_token_cannot_escalate_role_through_request_body(
    client: TestClient, viewer_headers: dict[str, str]
):
    response = client.post(
        "/api/v1/orders",
        json={
            "items": [{"product_id": 1, "quantity": 1}],
            "remark": "",
            "role": "admin",
        },
        headers={**viewer_headers, "Idempotency-Key": "role-escalation"},
    )
    assert response.status_code in {403, 422}
    assert response.json()["success"] is False


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-SEC-008")
def test_unsafe_request_id_is_replaced(
    client: TestClient, operator_headers: dict[str, str]
):
    unsafe = "bad id <script>"
    response = client.get(
        "/api/v1/products",
        headers={**operator_headers, "X-Request-ID": unsafe},
    )
    generated = response.headers["X-Request-ID"]
    assert generated != unsafe
    assert len(generated) == 32
    assert all(character in "0123456789abcdef" for character in generated)

    accepted = client.get(
        "/api/v1/products",
        headers={**operator_headers, "X-Request-ID": "req-valid_01.2"},
    )
    assert accepted.headers["X-Request-ID"] == "req-valid_01.2"


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-SEC-009")
def test_sensitive_query_value_is_masked_in_access_log(
    client: TestClient, operator_headers: dict[str, str]
):
    import json

    from app.config import BASE_DIR

    request_id = "obs-query-mask-001"
    secret = "super-secret-query-value"
    response = client.get(
        f"/api/v1/products?token={secret}",
        headers={**operator_headers, "X-Request-ID": request_id},
    )
    assert response.status_code == 200
    path = BASE_DIR / "logs" / "access.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    record = next(
        json.loads(line)
        for line in reversed(lines)
        if json.loads(line).get("http.request_id") == request_id
    )
    assert secret not in record["http.query"]
    assert "token=***" in record["http.query"]

