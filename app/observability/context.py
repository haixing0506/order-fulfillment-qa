from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_user_id: ContextVar[int | None] = ContextVar("user_id", default=None)
_username: ContextVar[str] = ContextVar("username", default="-")
_role: ContextVar[str] = ContextVar("role", default="-")


@dataclass(frozen=True)
class LogContext:
    request_id: str
    trace_id: str
    user_id: int | None
    username: str
    role: str


def bind_request(request_id: str, trace_id: str) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)


def bind_user(user_id: int, username: str, role: str) -> None:
    _user_id.set(user_id)
    _username.set(username)
    _role.set(role)


def clear_user() -> None:
    _user_id.set(None)
    _username.set("-")
    _role.set("-")


def current_request_id() -> str:
    return _request_id.get()


def current_trace_id() -> str:
    return _trace_id.get()


def snapshot() -> dict[str, object]:
    return asdict(
        LogContext(
            request_id=_request_id.get(),
            trace_id=_trace_id.get(),
            user_id=_user_id.get(),
            username=_username.get(),
            role=_role.get(),
        )
    )

