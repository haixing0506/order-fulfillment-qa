"""Start an isolated performance environment and run the Locust workload."""

from __future__ import annotations

import csv
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "reports" / "performance"
LOG_DIR = BASE_DIR / "logs" / "performance"
PERF_DB = BASE_DIR / "data" / "perf.db"
USERS = int(os.getenv("PERF_USERS", "30"))
SPAWN_RATE = int(os.getenv("PERF_SPAWN_RATE", "5"))
DURATION = os.getenv("PERF_DURATION", "40s")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log_event(event: str, **fields: object) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), "event": event, **fields}
    with (LOG_DIR / "performance_run.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(base_url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            response = httpx.get(f"{base_url}/health/ready", timeout=2)
            if response.status_code == 200:
                return
            last_error = response.text
        except Exception as exc:  # noqa: BLE001 - surfaced after timeout
            last_error = str(exc)
        time.sleep(0.4)
    raise RuntimeError(f"performance server did not become ready: {last_error}")


def prepare_stock(base_url: str) -> None:
    login = httpx.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": "admin", "password": "Admin@123"},
        timeout=10,
    )
    login.raise_for_status()
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    for product_id in (1, 4):
        response = httpx.patch(
            f"{base_url}/api/v1/products/{product_id}/stock",
            json={"stock": 1_000_000},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
    log_event("performance_stock_prepared", products=[1, 4], stock=1_000_000)


def read_aggregate() -> dict[str, object]:
    path = REPORT_DIR / "locust_stats.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    aggregate = next(
        (row for row in rows if row.get("Name") == "Aggregated"),
        rows[-1] if rows else {},
    )
    return aggregate


def run() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if PERF_DB.exists():
        PERF_DB.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{PERF_DB}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "OMS_ENV": "performance",
        "OMS_DATABASE_PATH": "data/perf.db",
        "OMS_LOG_DIR": "logs/performance",
        "OMS_SLOW_REQUEST_MS": "1000",
        "OMS_JWT_SECRET": "performance-only-secret-not-for-production",
    }
    console_path = LOG_DIR / "performance_console.log"
    console = console_path.open("w", encoding="utf-8")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=BASE_DIR,
        env=env,
        stdout=console,
        stderr=subprocess.STDOUT,
    )
    log_event(
        "performance_run_started",
        base_url=base_url,
        users=USERS,
        spawn_rate=SPAWN_RATE,
        duration=DURATION,
        server_pid=server.pid,
    )
    started = time.time()
    exit_code = 1
    try:
        wait_ready(base_url)
        prepare_stock(base_url)
        command = [
            sys.executable,
            "-m",
            "locust",
            "-f",
            "performance/locustfile.py",
            "--headless",
            "-u",
            str(USERS),
            "-r",
            str(SPAWN_RATE),
            "-t",
            DURATION,
            "--host",
            base_url,
            "--csv",
            str(REPORT_DIR / "locust"),
            "--html",
            str(REPORT_DIR / "locust-report.html"),
            "--only-summary",
            "--loglevel",
            "WARNING",
            "--exit-code-on-error",
            "1",
        ]
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
            check=False,
        )
        console.write(completed.stdout)
        console.flush()
        print(completed.stdout[-4000:])
        exit_code = completed.returncode
    except Exception as exc:  # noqa: BLE001 - logged as a failed performance run
        log_event("performance_run_error", error=str(exc))
        print(f"performance run failed: {exc}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        console.close()
        aggregate = read_aggregate()
        log_event(
            "performance_run_finished",
            exit_code=exit_code,
            elapsed_seconds=round(time.time() - started, 2),
            aggregated=aggregate,
        )
    summary = read_aggregate()
    if summary:
        print(
            "Aggregated: "
            f"requests={summary.get('Request Count')} "
            f"failures={summary.get('Failure Count')} "
            f"rps={summary.get('Requests/s')} "
            f"p95={summary.get('95%')}ms"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
