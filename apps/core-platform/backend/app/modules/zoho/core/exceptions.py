"""Zoho exception hierarchy.

All exceptions subclass the application's UpstreamError, so the global
exception handlers translate them into the unified JSON envelope without
any extra wiring. `zoho_code` carries Zoho's own error code (non-zero on
failure, e.g. 1002 = resource does not exist).
"""

from app.common.exception.errors import UpstreamError


class ZohoApiError(UpstreamError):
    """Base error for all Zoho API failures (HTTP 502 to our clients)."""

    code = "zoho_api_error"

    def __init__(self, msg: str, *, zoho_code: int | None = None, http_status: int | None = None, data: dict | None = None):
        payload = dict(data or {})
        if zoho_code is not None:
            payload["zoho_code"] = zoho_code
        if http_status is not None:
            payload["zoho_http_status"] = http_status
        super().__init__(msg, data=payload)
        self.zoho_code = zoho_code
        self.http_status = http_status


class ZohoAuthError(ZohoApiError):
    """Token refresh failed / refresh token revoked. Requires operator action."""

    code = "zoho_auth_error"


class ZohoNotFoundError(ZohoApiError):
    """Zoho resource does not exist (HTTP 404 / zoho code 1002)."""

    status_code = 404
    code = "zoho_not_found"


class ZohoValidationError(ZohoApiError):
    """Zoho rejected the payload (HTTP 400)."""

    status_code = 400
    code = "zoho_validation_error"


class ZohoRateLimitedError(ZohoApiError):
    """Out of retry budget against Zoho's rate limit (HTTP 429 upstream)."""

    status_code = 503
    code = "zoho_rate_limited"


class ZohoCircuitOpenError(ZohoApiError):
    """Circuit breaker open — Zoho is failing; requests short-circuited."""

    status_code = 503
    code = "zoho_circuit_open"
