from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppError(Exception):
    status_code: int
    code: str
    message: str
    details: list[dict[str, Any]] | dict[str, Any] | None = field(default=None)

    def __str__(self) -> str:
        return self.message


class UnauthorizedError(AppError):
    def __init__(self, message: str = "登录状态无效，请重新登录") -> None:
        super().__init__(401, "AUTH_UNAUTHORIZED", message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "当前角色无权执行该操作") -> None:
        super().__init__(403, "RBAC_FORBIDDEN", message)


class NotFoundError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(404, code, message)


class ConflictError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(409, code, message)

