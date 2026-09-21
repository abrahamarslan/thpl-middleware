"""Zoho core — the only layer that talks to Zoho.

Everything Zoho-related goes through this package, and every outbound call
passes the same gates:

    circuit breaker  → is this endpoint group healthy?         (breaker.py)
    governor         → may we spend a call right now?          (governor.py)
                       daily ceiling · pacing · rate · concurrency
    token manager    → one valid access token for the fleet    (auth.py)
    transport        → send, classify, decide                  (transport.py, policy.py)

Guarantees callers can rely on:
  * a request never fails with "invalid token" because of caching (single-flight
    refresh, 401 → invalidate-and-retry-once);
  * the configured daily call ceiling is never exceeded, and work suspends and
    resumes across the quota day boundary instead of failing;
  * a write whose outcome is unknown is never retried blindly;
  * a failed list page is an exception, never an empty page.

Docs: docs/zoho-sync-implementation/ (README.md indexes every component).
"""

from app.modules.zoho.core.auth import ZohoTokenManager, zoho_token_manager
from app.modules.zoho.core.breaker import ZohoCircuitBreaker, endpoint_group, zoho_breaker
from app.modules.zoho.core.errors import (
    ErrorCategory,
    ZohoAmbiguousOutcome,
    ZohoApiError,
    ZohoAuthError,
    ZohoAuthRevokedError,
    ZohoCircuitOpenError,
    ZohoContractError,
    ZohoError,
    ZohoNotFoundError,
    ZohoQuotaExhaustedError,
    ZohoRateLimitedError,
    ZohoTransientError,
    ZohoValidationError,
)
from app.modules.zoho.core.governor import Priority, zoho_governor
from app.modules.zoho.core.schemas import ZohoPageContext, ZohoResponse
from app.modules.zoho.core.transport import Api, ZohoClient, ZohoOp, ZohoPage, zoho_client

__all__ = [
    "Api",
    "ErrorCategory",
    "Priority",
    "ZohoAmbiguousOutcome",
    "ZohoApiError",
    "ZohoAuthError",
    "ZohoAuthRevokedError",
    "ZohoCircuitBreaker",
    "ZohoCircuitOpenError",
    "ZohoClient",
    "ZohoContractError",
    "ZohoError",
    "ZohoNotFoundError",
    "ZohoOp",
    "ZohoPage",
    "ZohoPageContext",
    "ZohoQuotaExhaustedError",
    "ZohoRateLimitedError",
    "ZohoResponse",
    "ZohoTokenManager",
    "ZohoTransientError",
    "ZohoValidationError",
    "endpoint_group",
    "zoho_breaker",
    "zoho_client",
    "zoho_governor",
    "zoho_token_manager",
]
