"""ForecastOps API application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .errors import register_exception_handlers
from .observability import RequestContextMiddleware, configure_logging
from .routers import alerts, audit, auth, datasets, health, inventory, jobs, runs
from .services import storage

logger = logging.getLogger("forecastops.startup")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Permitted-Cross-Domain-Policies": "none",
}


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth CSRF check on state-changing requests.

    Cookies are ``SameSite=Lax`` and ``HttpOnly``, which already blocks cross-site writes.
    This middleware additionally rejects an unsafe request whose ``Origin`` is neither an
    allowed origin nor the host it was sent to. Requests without an ``Origin`` header
    (curl, server-to-server) are allowed — they cannot carry a victim's ambient cookie.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and not self._allowed(origin, request):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "origin_not_allowed", "message": "Request origin is not allowed."}},
                )
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    @staticmethod
    def _allowed(origin: str, request: Request) -> bool:
        if origin in settings.allowed_origins or "*" in settings.allowed_origins:
            return True
        host = urlparse(origin).netloc
        candidates = {
            request.headers.get("host"),
            request.headers.get("x-forwarded-host"),
        }
        if host and host in {candidate for candidate in candidates if candidate}:
            return True
        # Browser hint: same-origin navigation survives dev proxies that rewrite Host.
        return request.headers.get("sec-fetch-site") == "same-origin"


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - FastAPI signature
    configure_logging(settings.log_level)
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.data_dir) / "datasets").mkdir(parents=True, exist_ok=True)
    storage.sweep_previews()
    storage.cleanup_temp_dir()
    logger.info(
        "ForecastOps API started (env=%s, execution_mode=%s, sqlite=%s)",
        settings.environment,
        settings.execution_mode,
        settings.is_sqlite,
    )
    yield
    from .services.queue import shutdown

    shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Demand & inventory planning API. All metrics are decision support from a single "
            "chronological holdout and are not real-world benchmarks."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-request-id", "x-idempotency-key"],
    )

    register_exception_handlers(app)

    # Health endpoints live at the root for container probes; the product API is versioned.
    app.include_router(health.router)
    for module in (auth, datasets, jobs, runs, inventory, alerts, audit):
        app.include_router(module.router, prefix="/api/v1")

    return app


app = create_app()
