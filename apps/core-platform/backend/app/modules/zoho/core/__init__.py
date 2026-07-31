"""Zoho Books core API layer.

Everything Zoho-related goes through this package. It guarantees that a
request to Zoho NEVER fails with "Invalid or expired token":

  - tokens are refreshed proactively (2-minute safety margin before expiry)
  - refresh is single-flight across every uvicorn/celery worker (Redis lock)
  - a 401 from Zoho invalidates the cached token and the request is retried
    once with a freshly minted token

Plus enterprise guards:
  - rate limiter   (Zoho Books: ~100 req/min/org)  -> ZohoRateLimiter
  - circuit breaker (per endpoint group)           -> ZohoCircuitBreaker
  - retry w/ backoff on 429/5xx/network            -> inside ZohoClient
"""

from app.modules.zoho.core.client import ZohoClient, zoho_client
from app.modules.zoho.core.exceptions import (
    ZohoApiError,
    ZohoAuthError,
    ZohoCircuitOpenError,
    ZohoNotFoundError,
    ZohoRateLimitedError,
)
from app.modules.zoho.core.schemas import ZohoPageContext, ZohoResponse
from app.modules.zoho.core.sync_client import ZohoSyncClient, zoho_sync_client

__all__ = [
    "ZohoClient",
    "zoho_client",
    "ZohoSyncClient",
    "zoho_sync_client",
    "ZohoResponse",
    "ZohoPageContext",
    "ZohoApiError",
    "ZohoAuthError",
    "ZohoNotFoundError",
    "ZohoRateLimitedError",
    "ZohoCircuitOpenError",
]
