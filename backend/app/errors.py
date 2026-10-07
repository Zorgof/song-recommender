"""Application errors and the handlers that render them as `{"error": {"code", "message"}}`."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors that are shown to the client with a stable `code`."""

    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    default_message = "The requested resource was not found."


class LLMUnavailableError(AppError):
    code = "llm_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The language model provider is unavailable."


class CatalogUnavailableError(AppError):
    code = "catalog_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "The music catalog is unavailable."


class STTUnavailableError(AppError):
    code = "stt_unavailable"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = "Speech-to-text is unavailable."


# Status codes raised by the framework itself (unknown route, wrong method, ...).
_HTTP_STATUS_CODES: dict[int, str] = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status_code)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Drop the echoed input: it may contain the user's full text or an uploaded file.
    details = [{k: v for k, v in err.items() if k != "input"} for err in exc.errors()]
    return JSONResponse(
        error_body("validation_error", "The request is invalid.", jsonable_encoder(details)),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    return JSONResponse(
        error_body(code, str(exc.detail)),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"method": request.method, "path": request.url.path})
    return JSONResponse(
        error_body(AppError.code, AppError.default_message),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
