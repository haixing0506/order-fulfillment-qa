from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import re
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings, settings as global_settings
from app.observability.context import snapshot

_CONFIGURED = False
_CONFIG_LOCK = threading.Lock()
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {
    "message",
    "asctime",
    "taskName",
}
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|pwd|token|authorization|secret|api[_-]?key|card[_-]?no)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(password|passwd|pwd|token|authorization|secret|api[_-]?key)"
    r"([\"']?\s*[:=]\s*)([\"']?)[^\"'\s,&}]+"
)
_BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_JWT_TEXT = re.compile(
    r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"
)


def mask_text(value: str) -> str:
    masked = _BEARER_TEXT.sub("Bearer ***", value)
    masked = _SENSITIVE_TEXT.sub(r"\1\2\3***", masked)
    return _JWT_TEXT.sub("***", masked)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                cleaned[str(key)] = "***"
            else:
                cleaned[str(key)] = sanitize(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, Path):
        return str(value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, environment: str, version: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.version = version
        self.host = socket.gethostname()
        self.pid = os.getpid()

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "environment": self.environment,
            "version": self.version,
            "host": self.host,
            "pid": self.pid,
            "thread": record.threadName,
            "message": mask_text(record.getMessage()),
        }
        payload.update(snapshot())
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = sanitize(value)
        if record.exc_info:
            payload["exception"] = sanitize(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = snapshot()
        rid = context["request_id"]
        if rid != "-":
            self._style._fmt = (
                "%(asctime)s | %(levelname)-7s | %(name)s | [%(request_id)s] "
                "%(message)s"
            )
            record.request_id = rid
        else:
            self._style._fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
        return super().format(record)


def _rotating_handler(
    path: Path, level: int, formatter: logging.Formatter
) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def configure_logging(config: Settings | None = None, force: bool = False) -> None:
    global _CONFIGURED
    config = config or global_settings
    with _CONFIG_LOCK:
        if _CONFIGURED and not force:
            return
        config.prepare_directories()
        level = getattr(logging, config.log_level.upper(), logging.INFO)
        json_formatter = JsonFormatter(
            config.service_name, config.environment, config.version
        )
        console_formatter = ConsoleFormatter(datefmt="%H:%M:%S")

        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(level)

        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(console_formatter)
        root.addHandler(console)
        root.addHandler(
            _rotating_handler(config.log_dir / "app.jsonl", level, json_formatter)
        )
        root.addHandler(
            _rotating_handler(
                config.log_dir / "error.jsonl", logging.ERROR, json_formatter
            )
        )

        for logger_name, filename in (
            ("app.access", "access.jsonl"),
            ("app.audit", "audit.jsonl"),
            ("app.security", "security.jsonl"),
        ):
            logger = logging.getLogger(logger_name)
            logger.handlers.clear()
            logger.setLevel(level)
            logger.propagate = False
            logger.addHandler(
                _rotating_handler(config.log_dir / filename, level, json_formatter)
            )

        for noisy in ("uvicorn.access", "httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _CONFIGURED = True
        logging.getLogger("app.bootstrap").info(
            "logging_configured",
            extra={
                "event": "logging_configured",
                "log_dir": str(config.log_dir),
                "hostname": platform.node(),
            },
        )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    return logging.getLogger("app.audit")


def get_access_logger() -> logging.Logger:
    return logging.getLogger("app.access")


def get_security_logger() -> logging.Logger:
    return logging.getLogger("app.security")

