from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.requests import Request


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def ok(
    request: Request, data: Any, status_code: int = 200, meta: dict | None = None
) -> JSONResponse:
    payload: dict[str, Any] = {
        "success": True,
        "data": jsonable_encoder(data),
        "meta": meta or {},
        "request_id": _request_id(request),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return JSONResponse(payload, status_code=status_code)


def fail(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    return JSONResponse(
        {
            "success": False,
            "error": {
                "code": code,
                "message": message,
                "details": details,
            },
            "request_id": _request_id(request),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        status_code=status_code,
    )

