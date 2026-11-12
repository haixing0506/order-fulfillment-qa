from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.responses import ok
from app.schemas import ProductCreate, StockUpdate
from app.security import get_current_user, require_roles
from app.services import catalog

router = APIRouter(prefix="/api/v1/products", tags=["商品与库存"])


@router.get("")
def list_products(
    request: Request,
    search: str = Query(default="", max_length=80),
    category: str = Query(default="", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    config = request.app.state.settings
    data = catalog.list_products(
        config.database_path,
        search=search,
        category=category,
        page=page,
        page_size=page_size,
        low_stock_threshold=config.low_stock_threshold,
    )
    return ok(request, data, meta=data["pagination"])


@router.get("/{product_id}")
def product_detail(
    product_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
):
    config = request.app.state.settings
    return ok(
        request,
        catalog.get_product(
            config.database_path, product_id, config.low_stock_threshold
        ),
    )


@router.post("", status_code=201)
def create_product(
    payload: ProductCreate,
    request: Request,
    user: dict = Depends(require_roles("admin")),
):
    config = request.app.state.settings
    return ok(
        request,
        catalog.create_product(config.database_path, payload.model_dump()),
        status_code=201,
    )


@router.patch("/{product_id}/stock")
def update_stock(
    product_id: int,
    payload: StockUpdate,
    request: Request,
    user: dict = Depends(require_roles("admin")),
):
    config = request.app.state.settings
    return ok(
        request,
        catalog.update_stock(config.database_path, product_id, payload.stock),
    )

