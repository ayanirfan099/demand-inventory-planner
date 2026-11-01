"""Liveness and readiness probes.

``/healthz`` answers without touching dependencies (safe for container restarts).
``/readyz`` verifies the database, the data directory and reports the queue mode, so a
deployment can distinguish "process up" from "able to run forecasts".
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from ..config import settings
from ..db import engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "forecastops-api", "environment": settings.environment}


@router.get("/readyz")
def readyz(response: Response) -> dict:
    checks: dict[str, dict] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": type(exc).__name__}

    data_dir = Path(settings.data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".ready-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["storage"] = {"status": "ok", "writable": True}
    except OSError as exc:
        checks["storage"] = {"status": "error", "detail": type(exc).__name__}

    queue_status: dict = {"mode": settings.execution_mode}
    if settings.execution_mode == "rq":
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
            queue_status["redis"] = "ok"
        except Exception as exc:
            queue_status["redis"] = f"unavailable ({type(exc).__name__})"
            queue_status["degraded"] = True
    checks["queue"] = queue_status

    healthy = all(check.get("status", "ok") == "ok" for key, check in checks.items() if key != "queue")
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if healthy else "degraded", "checks": checks, "pid": os.getpid()}
