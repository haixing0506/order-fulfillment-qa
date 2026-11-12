from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import connect, transaction
from app.errors import ConflictError, NotFoundError
from app.observability.audit import audit_event
from app.observability.logging import get_logger

catalog_logger = get_logger("app.catalog")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def serialize_product(row: Any, low_stock_threshold: int) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sku": row["sku"],
        "name": row["name"],
        "category": row["category"],
        "price": round(row["price_cents"] / 100, 2),
        "price_cents": row["price_cents"],
        "stock": row["stock"],
        "low_stock": row["stock"] <= low_stock_threshold,
        "is_active": bool(row["is_active"]),
        "updated_at": row["updated_at"],
    }


def list_products(
    db_path: Any,
    search: str = "",
    category: str = "",
    page: int = 1,
    page_size: int = 20,
    low_stock_threshold: int = 20,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    clauses = ["is_active = 1"]
    params: list[Any] = []
    if search:
        clauses.append("(name LIKE ? OR sku LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern])
    if category:
        clauses.append("category = ?")
        params.append(category)
    where = " AND ".join(clauses)
    conn = connect(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM products WHERE {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM products WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        categories = [
            row["category"]
            for row in conn.execute(
                "SELECT DISTINCT category FROM products WHERE is_active = 1 "
                "ORDER BY category"
            ).fetchall()
        ]
    finally:
        conn.close()
    return {
        "items": [serialize_product(row, low_stock_threshold) for row in rows],
        "categories": categories,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    }


def get_product(db_path: Any, product_id: int, low_stock_threshold: int = 20) -> dict:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NotFoundError("PRODUCT_NOT_FOUND", "商品不存在或已下架")
    return serialize_product(row, low_stock_threshold)


def create_product(db_path: Any, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    try:
        with transaction(db_path, immediate=True) as conn:
            cursor = conn.execute(
                "INSERT INTO products(sku, name, category, price_cents, stock, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    payload["sku"].upper(),
                    payload["name"],
                    payload["category"],
                    payload["price_cents"],
                    payload["stock"],
                    now,
                    now,
                ),
            )
            product_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise ConflictError("PRODUCT_SKU_EXISTS", "SKU 已存在") from None
        raise
    product = serialize_product(row, 20)
    audit_event(
        "catalog.product_created",
        resource_type="product",
        resource_id=product_id,
        detail={"sku": product["sku"], "stock": product["stock"]},
    )
    catalog_logger.info(
        "product_created",
        extra={"event": "product_created", "product.id": product_id},
    )
    return product


def update_stock(db_path: Any, product_id: int, stock: int) -> dict[str, Any]:
    with transaction(db_path, immediate=True) as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("PRODUCT_NOT_FOUND", "商品不存在或已下架")
        conn.execute(
            "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
            (stock, _now(), product_id),
        )
        updated = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    product = serialize_product(updated, 20)
    audit_event(
        "catalog.stock_updated",
        resource_type="product",
        resource_id=product_id,
        detail={"previous_stock": row["stock"], "new_stock": stock},
    )
    catalog_logger.info(
        "stock_updated",
        extra={
            "event": "stock_updated",
            "product.id": product_id,
            "stock.previous": row["stock"],
            "stock.new": stock,
        },
    )
    return product


def dashboard_summary(db_path: Any, low_stock_threshold: int = 20) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM orders GROUP BY status"
        ).fetchall()
        status_counts = {row["status"]: row["count"] for row in status_rows}
        product_count = conn.execute(
            "SELECT COUNT(*) AS c FROM products WHERE is_active = 1"
        ).fetchone()["c"]
        low_stock_count = conn.execute(
            "SELECT COUNT(*) AS c FROM products WHERE is_active = 1 AND stock <= ?",
            (low_stock_threshold,),
        ).fetchone()["c"]
        today = datetime.now(timezone.utc).date().isoformat()
        today_orders = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()["c"]
        total_orders = sum(status_counts.values())
        completed = status_counts.get("COMPLETED", 0)
        fulfilled_base = total_orders - status_counts.get("CANCELLED", 0)
        fulfillment_rate = (
            round(completed / fulfilled_base * 100, 1) if fulfilled_base else 0.0
        )
        latest_rows = conn.execute(
            "SELECT o.*, u.display_name AS customer FROM orders o "
            "JOIN users u ON u.id = o.user_id ORDER BY o.created_at DESC LIMIT 6"
        ).fetchall()
    finally:
        conn.close()
    return {
        "orders_total": total_orders,
        "orders_today": today_orders,
        "pending_orders": status_counts.get("CREATED", 0)
        + status_counts.get("PICKING", 0),
        "status_counts": status_counts,
        "product_count": product_count,
        "low_stock_count": low_stock_count,
        "fulfillment_rate": fulfillment_rate,
        "latest_orders": [
            {
                "id": row["id"],
                "order_no": row["order_no"],
                "status": row["status"],
                "total": round(row["total_cents"] / 100, 2),
                "customer": row["customer"],
                "created_at": row["created_at"],
            }
            for row in latest_rows
        ],
    }

