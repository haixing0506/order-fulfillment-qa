from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request

from app.responses import ok
from app.schemas import OrderCreate, OrderStatusUpdate
from app.security import get_current_user, require_roles
from app.services import orders

router = APIRouter(prefix="/api/v1/orders", tags=["订单履约"])


@router.get("")
def list_orders(
    request: Request,
    status: str = Query(default="", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    config = request.app.state.settings
    data = orders.list_orders(
        config.database_path, status=status, page=page, page_size=page_size
    )
    return ok(request, data, meta=data["pagination"])


@router.post("", status_code=201)
def create_order(
    payload: OrderCreate,
    request: Request,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=128
    ),
    user: dict = Depends(require_roles("admin", "operator")),
):
    config = request.app.state.settings
    data, replayed = orders.create_order(
        config.database_path,
        int(user["id"]),
        [item.model_dump() for item in payload.items],
        payload.remark,
        idempotency_key,
    )
    return ok(
        request,
        data,
        status_code=200 if replayed else 201,
        meta={"idempotent_replay": replayed},
    )


@router.get("/{order_id}")
def order_detail(
    order_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    config = request.app.state.settings
    return ok(request, orders.get_order(config.database_path, order_id))


@router.patch("/{order_id}/status")
def update_status(
    order_id: int,
    payload: OrderStatusUpdate,
    request: Request,
    user: dict = Depends(require_roles("admin", "operator")),
):
    config = request.app.state.settings
    return ok(
        request,
        orders.update_order_status(config.database_path, order_id, payload.status),
    )


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    request: Request,
    user: dict = Depends(require_roles("admin", "operator")),
):
    config = request.app.state.settings
    return ok(request, orders.cancel_order(config.database_path, order_id))

