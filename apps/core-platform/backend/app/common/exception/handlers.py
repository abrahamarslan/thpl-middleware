"""Global exception handlers — single JSON error envelope for all clients.

Deferred database constraints (the polymorphic integrity triggers built in
``core``) fire at COMMIT, which happens inside ``get_db`` — after the service
returned. Without a handler there, the client sees an opaque 500 even though
the database rejected the write for a reason it can act on. The
``IntegrityError`` handler maps SQLSTATE to a clean envelope; services still
pre-flight the common cases (brands/categories pattern) so the normal path
never reaches it.
"""

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.exception.errors import AppError

logger = structlog.get_logger("app.exception")

#: SQLSTATE → (status_code, code, message). The reference design's deferred
#: triggers raise 23503 (missing polymorphic target), 23514 (check) and 23P01
#: (exclusion / overlapping window); 23505 is a unique violation.
_SQLSTATE_MAP: dict[str, tuple[int, str, str]] = {
    "23505": (status.HTTP_409_CONFLICT, "conflict", "A record with these values already exists"),
    "23503": (status.HTTP_422_UNPROCESSABLE_ENTITY, "reference_violation",
              "The record references a row that does not exist"),
    "23514": (status.HTTP_422_UNPROCESSABLE_ENTITY, "check_violation",
              "The record violates a data rule"),
    "23P01": (status.HTTP_409_CONFLICT, "conflict", "The record overlaps an existing one"),
}


def _sqlstate(exc: Exception) -> str | None:
    """The Postgres SQLSTATE behind a SQLAlchemy error, if there is one."""
    orig = getattr(exc, "orig", None)
    return (
        getattr(orig, "sqlstate", None)
        or getattr(orig, "pgcode", None)
        or getattr(getattr(orig, "__cause__", None), "sqlstate", None)
    )


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

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        sqlstate = _sqlstate(exc)
        status_code, code, msg = _SQLSTATE_MAP.get(
            sqlstate or "", (status.HTTP_422_UNPROCESSABLE_ENTITY, "integrity_error",
                             "The write violates a database constraint")
        )
        # Parameters can carry secrets; log only the SQLSTATE and the driver's
        # own text, never the statement with bound values.
        logger.warning("integrity_error", sqlstate=sqlstate, path=request.url.path,
                       detail=str(getattr(exc, "orig", exc))[:300])
        return _envelope(request, status_code=status_code, code=code, msg=msg,
                         data={"sqlstate": sqlstate} if sqlstate else None)

    @app.exception_handler(StaleDataError)
    async def stale_data_handler(request: Request, exc: StaleDataError):
        logger.warning("stale_data", path=request.url.path, detail=str(exc)[:200])
        return _envelope(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="conflict",
            msg="The record changed since you loaded it; reload and retry",
        )

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
