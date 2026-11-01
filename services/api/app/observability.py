"""Structured request logging with request/job correlation ids."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_job_id: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="")

SENSITIVE_PATH_PREFIXES = ("/api/v1/auth",)


def get_request_id() -> str:
    return _request_id.get() or "-"


def get_job_id() -> str:
    return _job_id.get() or "-"


def set_job_id(value: str | int | None) -> None:
    _job_id.set(str(value) if value is not None else "")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_id(),
            "job_id": getattr(record, "job_id", None) or get_job_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel("WARNING")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, echo it, and log one structured line per request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        if len(request_id) > 64 or not request_id.isprintable():
            request_id = uuid.uuid4().hex
        token = _request_id.set(request_id)
        _job_id.set("")
        started = time.perf_counter()
        logger = logging.getLogger("forecastops.request")
        try:
            response = await call_next(request)
        except Exception:
            duration = round((time.perf_counter() - started) * 1000, 1)
            logger.exception(
                "request failed",
                extra={"context": {"method": request.method, "path": request.url.path, "duration_ms": duration}},
            )
            raise
        finally:
            _request_id.reset(token)
        duration = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        if not request.url.path.startswith(SENSITIVE_PATH_PREFIXES):
            logger.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={
                    "context": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": duration,
                    }
                },
            )
        return response
