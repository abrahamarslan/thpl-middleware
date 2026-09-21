"""Backwards-compatibility shim — the Zoho exception hierarchy moved.

The real definitions live in ``app.modules.zoho.core.errors`` together with
``ErrorCategory`` (docs/zoho-sync-implementation/errors-and-policy.md).
This module keeps the old import path working while modules migrate:

    from app.modules.zoho.core.exceptions import ZohoApiError   # legacy
    from app.modules.zoho.core.errors import ZohoTransientError  # preferred

``ZohoApiError`` is an alias of the new base ``ZohoError``, so existing
``except ZohoApiError`` / Celery ``autoretry_for`` call sites keep catching
every Zoho failure exactly as before.
"""

from app.modules.zoho.core.errors import (
    ErrorCategory,
    ZohoAmbiguousOutcome,
    ZohoApiError,
    ZohoAuthError,
    ZohoAuthRevokedError,
    ZohoAuthThrottledError,
    ZohoBudgetDeferred,
    ZohoCircuitOpenError,
    ZohoConflictError,
    ZohoContractError,
    ZohoError,
    ZohoForbiddenError,
    ZohoNotFoundError,
    ZohoQuotaExhaustedError,
    ZohoRateLimitedError,
    ZohoTransientError,
    ZohoUnclassifiedError,
    ZohoValidationError,
)

__all__ = [
    "ErrorCategory",
    "ZohoAmbiguousOutcome",
    "ZohoApiError",
    "ZohoAuthError",
    "ZohoAuthRevokedError",
    "ZohoAuthThrottledError",
    "ZohoBudgetDeferred",
    "ZohoCircuitOpenError",
    "ZohoConflictError",
    "ZohoContractError",
    "ZohoError",
    "ZohoForbiddenError",
    "ZohoNotFoundError",
    "ZohoQuotaExhaustedError",
    "ZohoRateLimitedError",
    "ZohoTransientError",
    "ZohoUnclassifiedError",
    "ZohoValidationError",
]
