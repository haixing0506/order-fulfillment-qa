from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.database import connect
from app.errors import AppError
from app.observability.audit import audit_event
from app.observability.context import bind_user
from app.observability.logging import get_logger, get_security_logger
from app.responses import ok
from app.schemas import LoginRequest
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])
auth_logger = get_logger("app.auth")
security_logger = get_security_logger()
DUMMY_PASSWORD_HASH = hash_password("timing-equalization-placeholder")


@router.post("/login")
def login(request: Request, payload: LoginRequest):
    config = request.app.state.settings
    conn = connect(config.database_path)
    try:
        row = conn.execute(
            "SELECT id, username, display_name, role, password_hash, is_active "
            "FROM users WHERE username = ?",
            (payload.username,),
        ).fetchone()
    finally:
        conn.close()

    stored_hash = row["password_hash"] if row is not None else DUMMY_PASSWORD_HASH
    password_valid = verify_password(payload.password, stored_hash)
    if row is None or not row["is_active"] or not password_valid:
        security_logger.warning(
            "login_failed",
            extra={
                "event": "login_failed",
                "auth.result": "FAILED",
                "auth.username": payload.username,
            },
        )
        audit_event(
            "auth.login",
            result="FAILED",
            resource_type="session",
            detail={"username": payload.username},
        )
        raise AppError(401, "AUTH_INVALID_CREDENTIALS", "用户名或密码错误")

    user = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }
    bind_user(int(user["id"]), user["username"], user["role"])
    request.state.user = user
    token, expires_in = create_access_token(
        user, config.jwt_secret, config.jwt_algorithm, config.token_ttl_minutes
    )
    audit_event(
        "auth.login",
        result="SUCCESS",
        resource_type="session",
        detail={"username": user["username"], "role": user["role"]},
    )
    auth_logger.info(
        "login_succeeded",
        extra={
            "event": "login_succeeded",
            "auth.username": user["username"],
            "auth.role": user["role"],
        },
    )
    return ok(
        request,
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": user,
        },
    )


@router.get("/me")
def me(request: Request, user: dict = Depends(get_current_user)):
    return ok(request, user)

