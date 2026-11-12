from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.observability.logging import sanitize

LOG_DIR = BASE_DIR / "logs"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _new_records(
    path: Path, predicate: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    return [record for record in _read_jsonl(path) if predicate(record)]


@pytest.mark.api
@pytest.mark.case("TC-OBS-001")
def test_access_log_correlates_request_id(
    client: TestClient, operator_headers: dict[str, str]
):
    request_id = "obs-access-0001"
    response = client.get(
        "/api/v1/products?page_size=5",
        headers={**operator_headers, "X-Request-ID": request_id},
    )
    assert response.status_code == 200
    records = _new_records(
        LOG_DIR / "access.jsonl",
        lambda record: record.get("http.request_id") == request_id,
    )
    assert records
    record = records[-1]
    assert record["http.method"] == "GET"
    assert record["http.path"] == "/api/v1/products"
    assert record["http.status_code"] == 200
    assert record["http.duration_ms"] >= 0
    assert record["event"] == "http_request"


@pytest.mark.api
@pytest.mark.case("TC-OBS-002")
def test_audit_log_records_order_creation(
    client: TestClient, operator_headers: dict[str, str]
):
    path = LOG_DIR / "audit.jsonl"
    before = len(_read_jsonl(path))
    response = client.post(
        "/api/v1/orders",
        json={"items": [{"product_id": 1, "quantity": 1}], "remark": "审计日志验证"},
        headers={**operator_headers, "Idempotency-Key": "obs-audit-001"},
    )
    assert response.status_code == 201
    order_id = response.json()["data"]["id"]
    new_records = _read_jsonl(path)[before:]
    matches = [
        record
        for record in new_records
        if record.get("audit.action") == "order.created"
        and record.get("audit.resource_id") == order_id
    ]
    assert matches
    assert matches[-1]["audit.result"] == "SUCCESS"
    assert matches[-1]["request_id"] == response.json()["request_id"]


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-OBS-003")
def test_security_log_records_failed_login(client: TestClient):
    path = LOG_DIR / "security.jsonl"
    before = len(_read_jsonl(path))
    username = "security-log-probe"
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Wrong@1234"},
    )
    assert response.status_code == 401
    new_records = _read_jsonl(path)[before:]
    matches = [
        record
        for record in new_records
        if record.get("event") == "login_failed"
        and record.get("auth.username") == username
    ]
    assert matches
    assert matches[-1]["auth.result"] == "FAILED"


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-OBS-004")
def test_log_sanitizer_masks_nested_secrets():
    payload = {
        "username": "operator",
        "password": "TopSecret@123",
        "nested": {"access_token": "abc.def.ghi", "note": "token=plain-value"},
        "items": [{"api_key": "key-123"}],
        "failure": (
            "headers={'Authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxIn0.c2lnbmF0dXJl'}"
        ),
    }
    cleaned = sanitize(payload)
    assert cleaned["password"] == "***"
    assert cleaned["nested"]["access_token"] == "***"
    assert "plain-value" not in cleaned["nested"]["note"]
    assert cleaned["items"][0]["api_key"] == "***"
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned["failure"]
    assert "c2lnbmF0dXJl" not in cleaned["failure"]
