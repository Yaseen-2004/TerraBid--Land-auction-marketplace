import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError, OperationalError, InterfaceError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error rendered as the platform's standard error envelope."""

    def __init__(
        self,
        message: str,
        error_code: str = "BAD_REQUEST",
        status_code: int = 400,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details
        self.headers = headers


_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def error_body(message: str, error_code: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": False, "message": message, "error_code": error_code}
    if details is not None:
        body["details"] = details
    return body


def _clean_validation_message(message: str) -> str:
    for prefix in ("Value error, ", "Assertion failed, "):
        if message.startswith(prefix):
            return message[len(prefix):]
    return message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.message, exc.error_code, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            location = [str(part) for part in err.get("loc", ()) if part not in ("body",)]
            errors.append({"field": ".".join(location), "message": _clean_validation_message(err.get("msg", ""))})
        message = errors[0]["message"] if errors else "Invalid request."
        if errors and errors[0]["field"]:
            message = f"{errors[0]['field']}: {message}"
        return JSONResponse(status_code=422, content=error_body(message, "VALIDATION_ERROR", errors))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(status_code=exc.status_code, content=error_body(message, code), headers=exc.headers)

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
        return JSONResponse(
            status_code=409,
            content=error_body("The request conflicts with existing data.", "CONFLICT"),
        )

    @app.exception_handler(RedisError)
    async def _redis_error(request: Request, exc: RedisError) -> JSONResponse:
        logger.error("Redis failure on %s %s: %r", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content=error_body(
                "The real-time auction engine is temporarily unavailable. Please retry.",
                "AUCTION_ENGINE_UNAVAILABLE",
            ),
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Database failure on %s %s: %r", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content=error_body("The database is temporarily unavailable. Please retry.", "DATABASE_UNAVAILABLE"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("An unexpected error occurred.", "INTERNAL_ERROR"),
        )
