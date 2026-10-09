import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details


def error_body(request: Request, status_code: int, code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.status_code, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo rejected values (which may contain passwords or other sensitive input).
        issues = [
            {"location": list(error.get("loc", ())), "message": error.get("msg"), "type": error.get("type")}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(request, 422, "validation_error", "Request validation failed", issues),
        )

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = "http_error"
        if exc.status_code == 401:
            code = "unauthenticated"
        elif exc.status_code == 403:
            code = "forbidden"
        elif exc.status_code == 404:
            code = "not_found"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc.status_code, code, str(exc.detail)),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API exception")
        return JSONResponse(
            status_code=500,
            content=error_body(request, 500, "internal_error", "An unexpected error occurred"),
        )
