"""One error format for every response:

    {"error": {"code": "not_found", "message": "...", "request_id": "..."}}

Validation errors add `details` (field locations and messages, never the
submitted values). Unexpected exceptions become 500 internal_error without
any internal text.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import errors as pg_errors
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.observability.context import request_id_var

logger = logging.getLogger(__name__)

DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    402: "quota_exceeded",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


class ApiError(HTTPException):
    """HTTPException with a stable machine-readable code and extra fields."""

    def __init__(self, status_code: int, code: str, message: str, headers=None, **extra) -> None:
        super().__init__(
            status_code, detail={"code": code, "message": message, **extra}, headers=headers
        )


def error_body(status: int, detail) -> dict:
    if isinstance(detail, dict):
        body = {
            "code": detail.get("code") or DEFAULT_CODES.get(status, "error"),
            "message": str(detail.get("message", "")),
            **{k: v for k, v in detail.items() if k not in ("code", "message")},
        }
    else:
        body = {"code": DEFAULT_CODES.get(status, "error"), "message": str(detail or "")}
    if rid := request_id_var.get():
        body["request_id"] = rid
    return {"error": body}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body(exc.status_code, exc.detail), exc.status_code, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": [str(p) for p in e.get("loc", ())],
                "msg": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()
        ]
        body = error_body(422, {"message": "Request validation failed.", "details": details})
        return JSONResponse(body, 422)

    @app.exception_handler(pg_errors.InsufficientPrivilege)
    async def rls_denied(_request: Request, _exc: Exception) -> JSONResponse:
        # Postgres refused (RLS or grants). Never echo database messages.
        return JSONResponse(error_body(403, "not allowed"), 403)

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse(error_body(500, "Something went wrong."), 500)
