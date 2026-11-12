from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from app.database import connect, transaction
from app.errors import ConflictError, NotFoundError
from app.observability.audit import audit_event
from app.observability.logging import get_logger

order_logger = get_logger("app.orders")

ALLOWED_TRANSITIONS = {
    "CREATED": {"PICKING"},
    "PICKING": {"SHIPPED"},
    "SHIPPED": {"COMPLETED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _generate_order_no() -> str:
    now = datetime.now(timezone.utc)
    return f"ORD-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _normalize_items(items: Iterable[dict[str, Any]]) -> list[dict[str, int]]:
    quantities: dict[int, int] = {}
    for item in items:
        product_id = int(item["product_id"])
        quantities[product_id] = quantities.get(product_id, 0) + int(item["quantity"])
    for product_id, quantity in quantities.items():
        if quantity > 99:
            raise ConflictError(
                "ORDER_ITEM_LIMIT_EXCEEDED",
                f"商品 {product_id} 的单次购买数量不能超过 99",
            )
    return [
        {"product_id": product_id, "quantity": quantity}
        for product_id, quantity in quantities.items()
    ]


def _request_hash(items: list[dict[str, int]], remark: str) -> str:
    canonical = json.dumps(
        {"items": items, "remark": remark}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _order_items(conn: Any, order_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return [
        {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "sku": row["sku"],
            "quantity": row["quantity"],
            "unit_price": round(row["unit_price_cents"] / 100, 2),
            "subtotal": round(row["subtotal_cents"] / 100, 2),
        }
        for row in rows
    ]


def serialize_order(
    conn: Any, row: Any, include_items: bool = False
) -> dict[str, Any]:
    item_count = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS c FROM order_items WHERE order_id = ?",
        (row["id"],),
    ).fetchone()["c"]
    payload = {
        "id": row["id"],
        "order_no": row["order_no"],
        "user_id": row["user_id"],
        "status": row["status"],
        "total": round(row["total_cents"] / 100, 2),
        "remark": row["remark"],
        "item_count": item_count,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_items:
        payload["items"] = _order_items(conn, row["id"])
    return payload


def get_order(
    db_path: Any, order_id: int, include_items: bool = True
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise NotFoundError("ORDER_NOT_FOUND", "订单不存在")
        return serialize_order(conn, row, include_items=include_items)
    finally:
        conn.close()


def create_order(
    db_path: Any,
    user_id: int,
    items: list[dict[str, Any]],
    remark: str,
    idempotency_key: str | None,
) -> tuple[dict[str, Any], bool]:
    normalized = _normalize_items(items)
    request_hash = _request_hash(normalized, remark)
    idempotency_key = (idempotency_key or "").strip() or uuid.uuid4().hex

    conn = connect(db_path)
    try:
        existing = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise ConflictError(
                    "ORDER_IDEMPOTENCY_CONFLICT",
                    "同一幂等键不能用于不同的订单内容",
                )
            order_logger.info(
                "order_idempotent_replay",
                extra={
                    "event": "order_idempotent_replay",
                    "order.id": existing["id"],
                    "idempotency.replayed": True,
                },
            )
            return serialize_order(conn, existing), True
    finally:
        conn.close()

    now = _now()
    with transaction(db_path, immediate=True) as conn:
        existing = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? AND idempotency_key = ?",
            (user_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise ConflictError(
                    "ORDER_IDEMPOTENCY_CONFLICT",
                    "同一幂等键不能用于不同的订单内容",
                )
            return serialize_order(conn, existing), True

        product_rows: dict[int, Any] = {}
        for item in normalized:
            product = conn.execute(
                "SELECT * FROM products WHERE id = ? AND is_active = 1",
                (item["product_id"],),
            ).fetchone()
            if product is None:
                raise NotFoundError(
                    "PRODUCT_NOT_FOUND", f"商品 {item['product_id']} 不存在或已下架"
                )
            product_rows[item["product_id"]] = product
            if product["stock"] < item["quantity"]:
                raise ConflictError(
                    "ORDER_STOCK_INSUFFICIENT",
                    f"{product['name']} 库存不足，当前可用 {product['stock']} 件",
                )

        total_cents = sum(
            product_rows[item["product_id"]]["price_cents"] * item["quantity"]
            for item in normalized
        )
        cursor = conn.execute(
            "INSERT INTO orders(order_no, user_id, status, total_cents, remark, "
            "idempotency_key, request_hash, created_at, updated_at) "
            "VALUES (?, ?, 'CREATED', ?, ?, ?, ?, ?, ?)",
            (
                _generate_order_no(),
                user_id,
                total_cents,
                remark,
                idempotency_key,
                request_hash,
                now,
                now,
            ),
        )
        order_id = cursor.lastrowid
        for item in normalized:
            product = product_rows[item["product_id"]]
            quantity = item["quantity"]
            updated = conn.execute(
                "UPDATE products SET stock = stock - ?, updated_at = ? "
                "WHERE id = ? AND stock >= ?",
                (quantity, now, item["product_id"], quantity),
            )
            if updated.rowcount != 1:
                raise ConflictError(
                    "ORDER_STOCK_INSUFFICIENT", f"{product['name']} 库存发生变化，请重试"
                )
            subtotal = product["price_cents"] * quantity
            conn.execute(
                "INSERT INTO order_items(order_id, product_id, product_name, sku, "
                "quantity, unit_price_cents, subtotal_cents) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    item["product_id"],
                    product["name"],
                    product["sku"],
                    quantity,
                    product["price_cents"],
                    subtotal,
                ),
            )
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        payload = serialize_order(conn, row, include_items=True)

    audit_event(
        "order.created",
        resource_type="order",
        resource_id=order_id,
        detail={
            "order_no": payload["order_no"],
            "items": len(normalized),
            "total": payload["total"],
        },
    )
    order_logger.info(
        "order_created",
        extra={
            "event": "order_created",
            "order.id": order_id,
            "order.no": payload["order_no"],
            "order.total": payload["total"],
            "order.items": len(normalized),
        },
    )
    return payload, False


def list_orders(
    db_path: Any,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("o.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = connect(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM orders o {where}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT o.*, u.display_name AS customer FROM orders o "
            f"JOIN users u ON u.id = o.user_id {where} "
            "ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        items = []
        for row in rows:
            payload = serialize_order(conn, row)
            payload["customer"] = row["customer"]
            items.append(payload)
    finally:
        conn.close()
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        },
    }


def update_order_status(db_path: Any, order_id: int, new_status: str) -> dict:
    with transaction(db_path, immediate=True) as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise NotFoundError("ORDER_NOT_FOUND", "订单不存在")
        current = row["status"]
        if new_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ConflictError(
                "ORDER_INVALID_TRANSITION",
                f"订单状态不能从 {current} 变更为 {new_status}",
            )
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _now(), order_id),
        )
        updated = conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        payload = serialize_order(conn, updated, include_items=True)
    audit_event(
        "order.status_changed",
        resource_type="order",
        resource_id=order_id,
        detail={
            "order_no": payload["order_no"],
            "from": current,
            "to": new_status,
        },
    )
    order_logger.info(
        "order_status_changed",
        extra={
            "event": "order_status_changed",
            "order.id": order_id,
            "status.from": current,
            "status.to": new_status,
        },
    )
    return payload


def cancel_order(db_path: Any, order_id: int) -> dict[str, Any]:
    with transaction(db_path, immediate=True) as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise NotFoundError("ORDER_NOT_FOUND", "订单不存在")
        if row["status"] == "CANCELLED":
            return serialize_order(conn, row, include_items=True)
        if row["status"] not in {"CREATED", "PICKING"}:
            raise ConflictError(
                "ORDER_CANNOT_CANCEL", f"{row['status']} 状态的订单不可取消"
            )
        items = conn.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = ?",
            (order_id,),
        ).fetchall()
        now = _now()
        for item in items:
            conn.execute(
                "UPDATE products SET stock = stock + ?, updated_at = ? WHERE id = ?",
                (item["quantity"], now, item["product_id"]),
            )
        conn.execute(
            "UPDATE orders SET status = 'CANCELLED', updated_at = ? WHERE id = ?",
            (now, order_id),
        )
        updated = conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        payload = serialize_order(conn, updated, include_items=True)
    audit_event(
        "order.cancelled",
        resource_type="order",
        resource_id=order_id,
        detail={"order_no": payload["order_no"], "restored_items": len(payload["items"])},
    )
    order_logger.info(
        "order_cancelled",
        extra={
            "event": "order_cancelled",
            "order.id": order_id,
            "order.no": payload["order_no"],
        },
    )
    return payload

