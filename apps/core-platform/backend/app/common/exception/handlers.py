"""Global exception handlers — single JSON error envelope for all clients."""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.exception.errors import AppError

logger = structlog.get_logger("app.exception")


def _envelope(request: Request, *, status_code: int, code: str, msg: str, data=None) -> ORJSONResponse:
    return ORJSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "msg": msg,
            "data": data,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def _serializable_errors(errors: list[dict]) -> list[dict]:
    """Make Pydantic's error list safe to serialise.

    A validator that raises ``ValueError`` (the documented way to reject a
    value) leaves the exception OBJECT in ``ctx['error']``. orjson cannot
    encode it, so the 422 turned into a 500 — the clear message replaced by an
    opaque server error. ``msg`` already carries the text, so the object is
    reduced to its string.
    """
    cleaned = []
    for error in errors:
        item = dict(error)
        ctx = item.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v))
                           for k, v in ctx.items()}
        if isinstance(item.get("input"), (bytes, bytearray)):
            item["input"] = "<binary>"
        cleaned.append(item)
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.warning("app_error", code=exc.code, msg=exc.msg, path=request.url.path)
        return _envelope(request, status_code=exc.status_code, code=exc.code, msg=exc.msg, data=exc.data or None)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return _envelope(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            msg="Request validation failed",
            data=_serializable_errors(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return _envelope(request, status_code=exc.status_code, code="http_error", msg=str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        # Full traceback goes to Loki; client gets an opaque 500 + request_id
        logger.exception("unhandled_exception", path=request.url.path)
        return _envelope(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            msg="Internal server error",
        )
