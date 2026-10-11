"""Turn exceptions into RFC 7807 problem+json responses.

Unexpected exceptions deliberately return a generic message. Echoing the
real exception text to the caller leaks table names, file paths and
library versions — useful to an attacker, useless to a user. The detail
goes to the logs instead, where it belongs.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.observability import get_logger

log = get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_problem(),
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "type": "/errors/validation_failed",
                "title": "validation_failed",
                "status": 422,
                "detail": "Some fields are not valid.",
                "errors": [
                    {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                    for e in exc.errors()
                ],
            },
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"/errors/http_{exc.status_code}",
                "title": "http_error",
                "status": exc.status_code,
                "detail": str(exc.detail),
            },
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "type": "/errors/internal_error",
                "title": "internal_error",
                "status": 500,
                # Deliberately generic: the real reason is in the logs.
                "detail": "Something went wrong on our side.",
            },
            media_type=PROBLEM_JSON,
        )
