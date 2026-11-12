from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    base_dir: Path = field(default_factory=lambda: BASE_DIR)
    environment: str = field(default_factory=lambda: os.getenv("OMS_ENV", "local"))
    service_name: str = "order-fulfillment"
    version: str = "1.0.0"
    database_path: Path = field(
        default_factory=lambda: BASE_DIR
        / os.getenv("OMS_DATABASE_PATH", "data/oms.db")
    )
    log_dir: Path = field(
        default_factory=lambda: BASE_DIR / os.getenv("OMS_LOG_DIR", "logs")
    )
    jwt_secret: str = field(
        default_factory=lambda: os.getenv(
            "OMS_JWT_SECRET", "local-dev-secret-change-me-before-use"
        )
    )
    jwt_algorithm: str = "HS256"
    token_ttl_minutes: int = field(
        default_factory=lambda: _read_int("OMS_TOKEN_TTL_MINUTES", 60)
    )
    log_level: str = field(default_factory=lambda: os.getenv("OMS_LOG_LEVEL", "INFO"))
    slow_request_ms: int = field(
        default_factory=lambda: _read_int("OMS_SLOW_REQUEST_MS", 800)
    )
    low_stock_threshold: int = 20

    def prepare_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "tests").mkdir(parents=True, exist_ok=True)
        (self.log_dir / "performance").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "reports" / "performance").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.prepare_directories()

