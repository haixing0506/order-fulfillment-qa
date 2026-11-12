from __future__ import annotations

from fastapi import APIRouter, Request

from app.responses import ok

router = APIRouter(prefix="/api/v1/system", tags=["系统"])


@router.get("/info")
def info(request: Request):
    config = request.app.state.settings
    return ok(
        request,
        {
            "service": config.service_name,
            "version": config.version,
            "environment": config.environment,
        },
    )

