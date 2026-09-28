"""Field-ops domain errors. Every one renders through the global handlers as the
``{code, msg, data, request_id}`` envelope; ``code`` is the stable, documented error code
(docs/fieldops/implementation-of-shift-visits-system.md §14.3)."""

from __future__ import annotations

from app.common.exception.errors import AppError, ConflictError, NotFoundError


class FieldOpsRuleError(AppError):
    """A business rule refused the request (422). ``code`` names WHICH rule."""

    status_code = 422

    def __init__(self, code: str, msg: str, *, data: dict | None = None):
        super().__init__(msg, data=data)
        self.code = code


class FieldOpsConflict(ConflictError):
    """The request conflicts with current state (409), e.g. a shift is already open."""

    def __init__(self, code: str, msg: str, *, data: dict | None = None):
        super().__init__(msg, data=data)
        self.code = code


class FieldOpsNotFound(NotFoundError):
    pass


__all__ = ["FieldOpsConflict", "FieldOpsNotFound", "FieldOpsRuleError"]
