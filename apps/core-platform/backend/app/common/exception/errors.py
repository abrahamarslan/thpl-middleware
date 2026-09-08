"""Domain exception hierarchy.

Services raise these; the global handlers in handlers.py translate them
into the unified JSON envelope. API code should never raise bare
HTTPException for business errors.
"""


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 400
    code: str = "app_error"

    def __init__(self, msg: str, *, data: dict | None = None):
        self.msg = msg
        self.data = data or {}
        super().__init__(msg)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UpstreamError(AppError):
    """A dependency (Zoho, Typst, ...) failed. 502 keeps blame upstream.

    Zoho-specific errors live in app.modules.zoho.core.exceptions and
    subclass this, so global handlers cover them automatically.
    """

    status_code = 502
    code = "upstream_error"
