from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from app.database import connect
from app.responses import ok

router = APIRouter(prefix="/health", tags=["健康检查"])


@router.get("/live")
def live(request: Request):
    return ok(request, {"status": "UP", "service": "order-fulfillment"})


@router.get("/ready")
def ready(request: Request):
    config = request.app.state.settings
    conn = connect(config.database_path)
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()
    return ok(
        request,
        {
            "status": "READY",
            "database": "UP",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )

