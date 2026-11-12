from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings as global_settings
from app.observability.context import bind_request, clear_user
from app.observability.logging import get_access_logger, get_logger, mask_text

request_logger = get_logger("app.request")
access_logger = get_access_logger()
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _request_id(value: str | None) -> str:
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        trace_id = request.headers.get("X-Trace-ID") or request_id
        bind_request(request_id, trace_id)
        clear_user()
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Process-Time-Ms"] = str(
                round((time.perf_counter() - started) * 1000, 2)
            )
            return response
        except Exception:
            request_logger.exception(
                "unhandled_request_exception",
                extra={
                    "event": "unhandled_request_exception",
                    "http.method": request.method,
                    "http.path": request.url.path,
                },
            )
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            client_ip = request.client.host if request.client else "-"
            query = mask_text(request.url.query)[:500]
            access_logger.info(
                "http_request",
                extra={
                    "event": "http_request",
                    "http.method": request.method,
                    "http.path": request.url.path,
                    "http.query": query,
                    "http.status_code": status_code,
                    "http.duration_ms": duration_ms,
                    "http.client_ip": client_ip,
                    "http.user_agent": request.headers.get("user-agent", "-"),
                    "http.request_id": request_id,
                },
            )
            app_settings = getattr(request.app.state, "settings", global_settings)
            slow_threshold = getattr(
                app_settings, "slow_request_ms", global_settings.slow_request_ms
            )
            if duration_ms >= slow_threshold:
                request_logger.warning(
                    "slow_request_detected",
                    extra={
                        "event": "slow_request_detected",
                        "http.method": request.method,
                        "http.path": request.url.path,
                        "http.status_code": status_code,
                        "http.duration_ms": duration_ms,
                        "slo_threshold_ms": slow_threshold,
                    },
                )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
        )
        return response

