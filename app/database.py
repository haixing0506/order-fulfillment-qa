from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.observability.logging import get_logger
from app.security import hash_password

logger = get_logger("app.database")

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL CHECK (
        status IN ('CREATED', 'PICKING', 'SHIPPED', 'COMPLETED', 'CANCELLED')
    ),
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    remark TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT,
    request_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    subtotal_cents INTEGER NOT NULL CHECK (subtotal_cents >= 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_status_created
    ON orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_user_created
    ON orders(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_items_order
    ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_products_category
    ON products(category, is_active);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(
    path: Path | str, immediate: bool = False
) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_database(path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()
    logger.info(
        "database_schema_ready",
        extra={"event": "database_schema_ready", "db.path": str(path)},
    )


def seed_database(path: Path | str) -> None:
    conn = connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if count:
            return
        now = datetime.now(timezone.utc)
        now_text = now.isoformat(timespec="seconds")
        users = [
            ("admin", "Admin@123", "系统管理员", "admin"),
            ("operator", "Operator@123", "履约专员", "operator"),
            ("viewer", "Viewer@123", "业务审核员", "viewer"),
        ]
        conn.execute("BEGIN IMMEDIATE")
        for username, password, display_name, role in users:
            conn.execute(
                "INSERT INTO users(username, password_hash, display_name, role, "
                "is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (username, hash_password(password), display_name, role, now_text),
            )

        products = [
            ("SKU-1001", "星海降噪耳机", "音频设备", 59900, 180),
            ("SKU-1002", "曜石机械键盘", "电脑外设", 45900, 120),
            ("SKU-1003", "云杉显示器支架", "桌面设备", 32900, 96),
            ("SKU-1004", "轻羽无线鼠标", "电脑外设", 19900, 240),
            ("SKU-1005", "远山便携音箱", "音频设备", 36900, 65),
            ("SKU-1006", "澄川 USB-C 扩展坞", "电脑外设", 28900, 88),
            ("SKU-1007", "岩层移动硬盘 2TB", "存储设备", 79900, 42),
            ("SKU-1008", "白露智能手环", "智能穿戴", 69900, 8),
            ("SKU-1009", "松风人体工学椅", "办公家具", 129900, 15),
            ("SKU-1010", "青屿桌面灯", "桌面设备", 15900, 150),
            ("SKU-1011", "拾光高清摄像头", "电脑外设", 49900, 74),
            ("SKU-1012", "行舟标签打印机", "办公设备", 89900, 36),
        ]
        for sku, name, category, price, stock in products:
            conn.execute(
                "INSERT INTO products(sku, name, category, price_cents, stock, "
                "is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (sku, name, category, price, stock, now_text, now_text),
            )
        conn.execute("COMMIT")

        seeded_orders = [
            (2, "CREATED", 1, 1, "客户要求工作日送达", 1),
            (2, "PICKING", 4, 2, "礼品包装", 2),
            (2, "SHIPPED", 7, 1, "", 4),
            (2, "COMPLETED", 2, 1, "", 7),
            (2, "COMPLETED", 10, 2, "部门采购", 10),
            (2, "CANCELLED", 5, 1, "客户取消", 12),
            (2, "SHIPPED", 6, 1, "加急", 18),
            (2, "CREATED", 3, 1, "", 20),
        ]
        for index, (user_id, status, product_id, qty, remark, hours_ago) in enumerate(
            seeded_orders, start=1
        ):
            created = now - timedelta(hours=hours_ago)
            created_text = created.isoformat(timespec="seconds")
            product = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            total = int(product["price_cents"]) * qty
            order_no = f"ORD-{created:%Y%m%d}-{index:04d}"
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO orders(order_no, user_id, status, total_cents, remark, "
                "idempotency_key, request_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    order_no,
                    user_id,
                    status,
                    total,
                    remark,
                    f"seed-{index}",
                    f"seed-hash-{index}",
                    created_text,
                    created_text,
                ),
            )
            order_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO order_items(order_id, product_id, product_name, sku, "
                "quantity, unit_price_cents, subtotal_cents) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    order_id,
                    product_id,
                    product["name"],
                    product["sku"],
                    qty,
                    product["price_cents"],
                    total,
                ),
            )
            if status != "CANCELLED":
                conn.execute(
                    "UPDATE products SET stock = stock - ?, updated_at = ? "
                    "WHERE id = ?",
                    (qty, now_text, product_id),
                )
            conn.execute("COMMIT")
        logger.info(
            "database_seed_completed",
            extra={
                "event": "database_seed_completed",
                "seed.users": len(users),
                "seed.products": len(products),
                "seed.orders": len(seeded_orders),
            },
        )
    finally:
        conn.close()

