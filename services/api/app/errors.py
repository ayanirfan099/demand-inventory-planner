"""Typed application errors and RFC-shaped JSON error responses.

Clients receive a stable machine-readable ``code`` and a human message that never contains
stack traces, SQL or filesystem paths.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .observability import get_request_id

logger = logging.getLogger("forecastops.errors")


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"
    message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, details: dict | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"
    message = "Sign in to continue."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "Your role does not allow this action."


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "payload_too_large"
    message = "The uploaded file is too large."


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Try again later."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A dependency is unavailable. Try again shortly."


def error_body(code: str, message: str, *, details: dict | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message, "request_id": get_request_id()}}
    if details:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.exception("application error: %s", exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, details=exc.details or None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field locations and messages are echoed; submitted values are not.
        details = {
            "fields": [
                {"loc": ".".join(str(part) for part in error["loc"][1:]), "message": error["msg"]}
                for error in exc.errors()[:10]
            ]
        }
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_body("validation_error", "Some fields are invalid.", details=details),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "Something went wrong on our side."),
        )
