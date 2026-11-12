from __future__ import annotations

import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.main import create_app
from app.observability.logging import JsonFormatter

TEST_RUN_STARTED = time.time()
TEST_CASE_IDS: dict[str, str] = {}
TEST_LOG_DIR = BASE_DIR / "logs" / "tests"
TEST_LOG_DIR.mkdir(parents=True, exist_ok=True)


def pytest_configure(config: pytest.Config) -> None:
    logger = logging.getLogger("qa.test_runner")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.handlers.RotatingFileHandler(
        TEST_LOG_DIR / "test_execution.jsonl",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(JsonFormatter("qa-test-runner", "test", "1.0.0"))
    logger.addHandler(handler)
    logger.info(
        "test_session_started",
        extra={"event": "test_session_started", "runner": "pytest"},
    )


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        marker = item.get_closest_marker("case")
        if marker and marker.args:
            TEST_CASE_IDS[item.nodeid] = str(marker.args[0])


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    should_log = report.when == "call" or (
        report.when == "setup" and (report.failed or report.skipped)
    )
    if not should_log:
        return
    logger = logging.getLogger("qa.test_runner")
    if report.failed:
        outcome = "FAILED"
    elif report.skipped:
        outcome = "SKIPPED"
    else:
        outcome = "PASSED"
    extra: dict[str, Any] = {
        "event": "test_finished",
        "test.nodeid": report.nodeid,
        "test.case_id": TEST_CASE_IDS.get(report.nodeid, "-"),
        "test.outcome": outcome,
        "test.duration_ms": round(report.duration * 1000, 2),
        "test.module": report.nodeid.split("::", 1)[0],
    }
    if report.failed:
        extra["test.failure"] = str(report.longrepr)[-2500:]
    if report.skipped:
        extra["test.skip_reason"] = str(report.longrepr)
    logger.info("test_finished", extra=extra)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    logger = logging.getLogger("qa.test_runner")
    stats = session.testscollected
    logger.info(
        "test_session_finished",
        extra={
            "event": "test_session_finished",
            "test.collected": stats,
            "test.exit_status": exitstatus,
            "test.elapsed_seconds": round(time.time() - TEST_RUN_STARTED, 2),
        },
    )


@pytest.fixture()
def app_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        log_dir=BASE_DIR / "logs",
        environment="test",
        jwt_secret="unit-test-secret-with-enough-entropy",
        token_ttl_minutes=60,
        slow_request_ms=800,
    )


@pytest.fixture()
def client(app_settings: Settings) -> Iterator[TestClient]:
    app = create_app(app_settings)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def login_headers(
    client: TestClient, username: str, password: str
) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "admin", "Admin@123")


@pytest.fixture()
def operator_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "operator", "Operator@123")


@pytest.fixture()
def viewer_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "viewer", "Viewer@123")


def response_data(response: Any) -> Any:
    payload = response.json()
    assert payload["success"] is True, payload
    return payload["data"]


def product_by_id(client: TestClient, headers: dict[str, str], product_id: int) -> dict:
    response = client.get(f"/api/v1/products/{product_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response_data(response)


@pytest.fixture()
def order_payload() -> dict[str, Any]:
    return {
        "items": [
            {"product_id": 1, "quantity": 2},
            {"product_id": 4, "quantity": 1},
        ],
        "remark": "自动化测试订单",
    }


@pytest.fixture()
def json_dump(tmp_path: Path):
    def dump(name: str, payload: Any) -> Path:
        path = tmp_path / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    return dump

