from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ForbiddenError, UnauthorizedError
from app.observability.audit import audit_event
from app.observability.context import bind_user
from app.observability.logging import get_security_logger

PBKDF2_ITERATIONS = 260_000
bearer_scheme = HTTPBearer(auto_error=False)
security_logger = get_security_logger()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_access_token(
    user: dict[str, Any], secret: str, algorithm: str, ttl_minutes: int
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl_minutes)
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=algorithm), ttl_minutes * 60


def decode_access_token(token: str, secret: str, algorithm: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[algorithm])


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None:
        security_logger.warning(
            "authentication_missing",
            extra={"event": "authentication_missing", "auth.result": "MISSING"},
        )
        raise UnauthorizedError("缺少访问令牌")

    config = request.app.state.settings
    try:
        payload = decode_access_token(
            credentials.credentials, config.jwt_secret, config.jwt_algorithm
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        security_logger.warning(
            "authentication_token_invalid",
            extra={"event": "authentication_token_invalid", "auth.result": "INVALID"},
        )
        raise UnauthorizedError("访问令牌无效或已过期") from None

    from app.database import connect

    conn = connect(config.database_path)
    try:
        row = conn.execute(
            "SELECT id, username, display_name, role, is_active FROM users "
            "WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row["is_active"]:
        security_logger.warning(
            "authentication_user_inactive",
            extra={"event": "authentication_user_inactive", "auth.result": "INACTIVE"},
        )
        raise UnauthorizedError("账号不存在或已停用")

    user = dict(row)
    bind_user(int(user["id"]), str(user["username"]), str(user["role"]))
    request.state.user = user
    return user


def require_roles(*allowed_roles: str) -> Callable[..., dict[str, Any]]:
    def dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in allowed_roles:
            audit_event(
                action="rbac.denied",
                result="DENIED",
                resource_type="endpoint",
                detail={
                    "required_roles": sorted(allowed_roles),
                    "actual_role": user["role"],
                },
            )
            security_logger.warning(
                "rbac_access_denied",
                extra={
                    "event": "rbac_access_denied",
                    "auth.required_roles": sorted(allowed_roles),
                    "auth.actual_role": user["role"],
                },
            )
            raise ForbiddenError()
        return user

    return dependency

