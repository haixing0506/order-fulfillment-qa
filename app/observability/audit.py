from __future__ import annotations

from typing import Any

from app.observability.logging import get_audit_logger


def audit_event(
    action: str,
    result: str = "SUCCESS",
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    get_audit_logger().info(
        "business_audit",
        extra={
            "event": "business_audit",
            "audit.action": action,
            "audit.result": result,
            "audit.resource_type": resource_type or "-",
            "audit.resource_id": resource_id if resource_id is not None else "-",
            "audit.detail": detail or {},
        },
    )

