from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.responses import ok
from app.security import get_current_user
from app.services.catalog import dashboard_summary

router = APIRouter(prefix="/api/v1/dashboard", tags=["工作台"])


@router.get("/summary")
def summary(request: Request, user: dict = Depends(get_current_user)):
    config = request.app.state.settings
    return ok(
        request,
        dashboard_summary(config.database_path, config.low_stock_threshold),
    )

