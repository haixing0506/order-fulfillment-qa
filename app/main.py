from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, catalog, dashboard, health, orders, system
from app.config import Settings, settings as default_settings
from app.database import init_database, seed_database
from app.errors import AppError
from app.observability.logging import configure_logging, get_logger
from app.observability.middleware import (
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.responses import fail

logger = get_logger("app.lifecycle")


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or default_settings
    config.prepare_directories()
    configure_logging(config)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        init_database(config.database_path)
        seed_database(config.database_path)
        logger.info(
            "application_started",
            extra={
                "event": "application_started",
                "service.version": config.version,
                "deployment.environment": config.environment,
                "db.path": str(config.database_path),
            },
        )
        started = time.perf_counter()
        try:
            yield
        finally:
            uptime = round(time.perf_counter() - started, 2)
            logger.info(
                "application_stopped",
                extra={"event": "application_stopped", "uptime_seconds": uptime},
            )

    application = FastAPI(
        title="订单履约平台 API",
        version=config.version,
        description="用于功能测试、性能测试和质量工程演示的订单履约系统。",
        lifespan=lifespan,
        docs_url="/api/docs" if config.environment != "production" else None,
        redoc_url=None,
    )
    application.state.settings = config
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestContextMiddleware)

    base_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    application.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")
    reports_dir = config.base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    application.mount("/reports", StaticFiles(directory=str(reports_dir)), name="reports")

    for router in (
        health.router,
        system.router,
        auth.router,
        catalog.router,
        orders.router,
        dashboard.router,
    ):
        application.include_router(router)

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        logger.warning(
            "application_error",
            extra={
                "event": "application_error",
                "error.code": exc.code,
                "http.status_code": exc.status_code,
                "error.message": exc.message,
            },
        )
        return fail(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        logger.info(
            "request_validation_failed",
            extra={
                "event": "request_validation_failed",
                "validation.error_count": len(details),
                "validation.errors": details,
            },
        )
        return fail(
            request,
            422,
            "VALIDATION_ERROR",
            "请求参数校验失败",
            details,
        )

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        message = {
            404: "请求的资源不存在",
            405: "请求方法不被允许",
        }.get(exc.status_code, str(exc.detail))
        return fail(request, exc.status_code, "HTTP_ERROR", message)

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception(
            "unexpected_application_exception",
            extra={"event": "unexpected_application_exception"},
        )
        return fail(
            request,
            500,
            "INTERNAL_ERROR",
            "系统繁忙，请稍后重试",
        )

    @application.get("/", include_in_schema=False)
    async def dashboard_page(request: Request):
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"app_version": config.version},
        )

    @application.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"app_version": config.version},
        )

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return RedirectResponse("/static/favicon.svg", status_code=302)

    return application


app = create_app()

