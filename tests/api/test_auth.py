from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.security import decode_access_token


@pytest.mark.api
@pytest.mark.case("TC-AUTH-001")
def test_admin_login_returns_token_and_profile(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Admin@123"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["token_type"] == "bearer"
    assert payload["data"]["user"]["role"] == "admin"
    assert payload["data"]["user"]["username"] == "admin"
    assert payload["data"]["access_token"]


@pytest.mark.api
@pytest.mark.case("TC-AUTH-002")
def test_login_rejects_wrong_password_without_user_enumeration(
    client: TestClient,
):
    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Wrong@1234"},
    )
    unknown_user = client.post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "Wrong@1234"},
    )
    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert (
        wrong_password.json()["error"]["message"]
        == unknown_user.json()["error"]["message"]
    )
    assert wrong_password.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


@pytest.mark.api
@pytest.mark.case("TC-AUTH-003")
def test_login_validates_short_password(client: TestClient):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "123"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.api
@pytest.mark.case("TC-AUTH-004")
def test_me_requires_bearer_token(client: TestClient):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


@pytest.mark.api
@pytest.mark.case("TC-AUTH-005")
def test_expired_token_is_rejected(client: TestClient):
    config = client.app.state.settings
    expired = jwt.encode(
        {
            "sub": "2",
            "role": "operator",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-AUTH-006")
def test_tampered_token_signature_is_rejected(client: TestClient):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "Operator@123"},
    )
    token = login.json()["data"]["access_token"]
    config = client.app.state.settings
    token = token[:-3] + ("abc" if token[-3:] != "abc" else "xyz")
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.api
@pytest.mark.case("TC-AUTH-007")
def test_token_contains_expected_claims(client: TestClient):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "Operator@123"},
    )
    token = login.json()["data"]["access_token"]
    config = client.app.state.settings
    claims = decode_access_token(token, config.jwt_secret, config.jwt_algorithm)
    assert claims["sub"] == "2"
    assert claims["role"] == "operator"
    assert claims["jti"]
    assert claims["exp"] > claims["iat"]


@pytest.mark.api
@pytest.mark.security
@pytest.mark.case("TC-AUTH-008")
def test_unknown_user_still_runs_password_verification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    calls: list[str] = []

    from app.api import auth as auth_module

    original = auth_module.verify_password

    def spy(password: str, encoded: str) -> bool:
        calls.append(encoded)
        return original(password, encoded)

    monkeypatch.setattr(auth_module, "verify_password", spy)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "nobody-here", "password": "Wrong@1234"},
    )
    assert response.status_code == 401
    assert calls == [auth_module.DUMMY_PASSWORD_HASH]

