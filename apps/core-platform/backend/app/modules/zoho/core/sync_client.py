"""Synchronous Zoho client for Celery tasks.

Celery tasks run in synchronous worker processes, so they cannot use the
async client. This client shares the SAME Redis keys as ZohoTokenManager —
API and workers always present one shared token, and the single-flight
refresh lock coordinates across both worlds.

The async ZohoClient is the canonical implementation; keep behaviour in sync.
"""

import time
import uuid

import httpx
import redis as redis_sync
import structlog

from app.core.conf import settings
from app.modules.zoho.core.exceptions import (
    ZohoApiError,
    ZohoAuthError,
    ZohoNotFoundError,
    ZohoRateLimitedError,
    ZohoValidationError,
)
from app.modules.zoho.core.schemas import ZohoResponse
from app.modules.zoho.core.token_manager import LOCK_KEY, THROTTLE_KEY, TOKEN_KEY

logger = structlog.get_logger("app.zoho.sync_client")

_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 1.5
_BACKOFF_MAX = 30.0
_RL_WINDOW_KEY = "zoho:rl:{window}"


class ZohoSyncClient:
    def __init__(self) -> None:
        self._redis = redis_sync.from_url(settings.REDIS_URL, decode_responses=True)
        self._http = httpx.Client(
            base_url=settings.ZOHO_API_BASE_URL,
            timeout=settings.ZOHO_TIMEOUT_SECONDS,
        )

    # ── Token (same Redis keys / locking protocol as ZohoTokenManager) ──────

    def _get_token(self) -> str:
        token = self._redis.get(TOKEN_KEY)
        if token:
            return token

        if self._redis.set(LOCK_KEY, "1", nx=True, ex=30):
            try:
                token = self._redis.get(TOKEN_KEY)
                return token if token else self._refresh_token()
            finally:
                self._redis.delete(LOCK_KEY)

        for _ in range(80):  # wait up to 20s for the lock holder
            time.sleep(0.25)
            token = self._redis.get(TOKEN_KEY)
            if token:
                return token
        raise ZohoAuthError("Timed out waiting for Zoho token refresh by another worker")

    def _refresh_token(self) -> str:
        if not settings.ZOHO_REFRESH_TOKEN:
            raise ZohoAuthError("ZOHO_REFRESH_TOKEN is not configured")

        count = self._redis.incr(THROTTLE_KEY)
        if count == 1:
            self._redis.expire(THROTTLE_KEY, 600)
        if count > 8:
            raise ZohoAuthError("Zoho token refresh throttle reached (sync client)")

        logger.info("zoho_token_refresh_start", client="sync")
        resp = httpx.post(
            f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token",
            params={
                "refresh_token": settings.ZOHO_REFRESH_TOKEN,
                "client_id": settings.ZOHO_CLIENT_ID,
                "client_secret": settings.ZOHO_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            timeout=settings.ZOHO_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            raise ZohoAuthError("Zoho token refresh failed", http_status=resp.status_code)
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise ZohoAuthError(f"Zoho token refresh error: {payload.get('error', 'no access_token')}")
        ttl = max(int(payload.get("expires_in", 3600)) - settings.ZOHO_TOKEN_REFRESH_MARGIN, 60)
        self._redis.set(TOKEN_KEY, token, ex=ttl)
        logger.info("zoho_token_refresh_ok", client="sync", cached_ttl=ttl)
        return token

    # ── Rate limiting (same global Redis window as the async limiter) ───────

    def _acquire_rate_slot(self) -> None:
        waited = 0.0
        while True:
            key = _RL_WINDOW_KEY.format(window=int(time.time() // 60))
            count = self._redis.incr(key)
            if count == 1:
                self._redis.expire(key, 120)
            if count <= settings.ZOHO_RATE_LIMIT_PER_MINUTE:
                return
            sleep_for = 60 - (time.time() % 60) + 0.05
            waited += sleep_for
            if waited > 90:
                raise ZohoRateLimitedError("Local Zoho rate-limit budget exhausted (sync client)")
            logger.warning("zoho_rate_limit_window_full", client="sync", sleeping=round(sleep_for, 1))
            time.sleep(sleep_for)

    # ── Public API ───────────────────────────────────────────────────────────

    def get(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return self.request("POST", path, json=json, params=params)

    def put(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return self.request("PUT", path, json=json, params=params)

    def delete(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        return self.request("DELETE", path, params=params)

    def paginate(self, path: str, *, params: dict | None = None, per_page: int = 200, max_pages: int | None = None):
        """Generator over every page of a list endpoint (for sync tasks)."""
        page = 1
        while True:
            response = self.get(path, params={**(params or {}), "page": page, "per_page": per_page})
            yield response
            ctx = response.page_context
            if ctx is None or not ctx.has_more_page:
                return
            page += 1
            if max_pages is not None and page > max_pages:
                return

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> ZohoResponse:
        request_id = f"zoho-task-{uuid.uuid4().hex[:12]}"
        query = {"organization_id": settings.ZOHO_ORGANIZATION_ID, **(params or {})}

        token_retried = False
        attempt = 0
        while True:
            attempt += 1
            self._acquire_rate_slot()
            token = self._get_token()
            started = time.perf_counter()
            try:
                resp = self._http.request(
                    method, path, params=query, json=json,
                    headers={
                        "Authorization": f"Zoho-oauthtoken {token}",
                        "X-Request-Id": request_id,
                        "Accept": "application/json",
                    },
                )
            except httpx.TransportError as e:
                if attempt >= _MAX_ATTEMPTS:
                    raise ZohoApiError(f"Zoho transport error after {attempt} attempts: {e}") from e
                self._sleep_backoff(attempt, reason="transport_error", path=path)
                continue

            logger.info(
                "zoho_api_call", client="sync",
                method=method, path=path, status=resp.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                attempt=attempt, zoho_request_id=request_id,
            )

            if resp.status_code == 401:
                self._redis.delete(TOKEN_KEY)
                if token_retried:
                    raise ZohoApiError("Zoho rejected a freshly refreshed token (401)", http_status=401)
                token_retried = True
                continue

            if resp.status_code == 429:
                if attempt >= _MAX_ATTEMPTS:
                    raise ZohoRateLimitedError("Zoho rate limit exceeded; retries exhausted", http_status=429)
                retry_after = float(resp.headers.get("Retry-After", 0)) or None
                self._sleep_backoff(attempt, fixed=retry_after, reason="429", path=path)
                continue

            if resp.status_code >= 500:
                if attempt >= _MAX_ATTEMPTS:
                    raise ZohoApiError(f"Zoho server error {resp.status_code}; retries exhausted",
                                       http_status=resp.status_code)
                self._sleep_backoff(attempt, reason=f"http_{resp.status_code}", path=path)
                continue

            return self._finalise(resp, method=method, path=path, request_id=request_id)

    def _finalise(self, resp: httpx.Response, *, method: str, path: str, request_id: str) -> ZohoResponse:
        try:
            payload = resp.json()
        except ValueError:
            payload = {"code": -1, "message": resp.text[:500]}

        response = ZohoResponse.from_payload(request_id=request_id, http_status=resp.status_code, payload=payload)
        if response.ok:
            return response

        logger.warning("zoho_api_error", client="sync", method=method, path=path,
                       status=resp.status_code, zoho_code=response.zoho_code, zoho_message=response.message)
        if resp.status_code == 404 or response.zoho_code == 1002:
            raise ZohoNotFoundError(response.message or "Zoho resource not found",
                                    zoho_code=response.zoho_code, http_status=resp.status_code)
        if resp.status_code == 400:
            raise ZohoValidationError(response.message or "Zoho rejected the request",
                                      zoho_code=response.zoho_code, http_status=resp.status_code)
        raise ZohoApiError(response.message or f"Zoho API error (code {response.zoho_code})",
                           zoho_code=response.zoho_code, http_status=resp.status_code)

    @staticmethod
    def _sleep_backoff(attempt: int, *, fixed: float | None = None, reason: str = "", path: str = "") -> None:
        delay = min(fixed if fixed is not None else _BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_MAX)
        logger.warning("zoho_retry", client="sync", path=path, reason=reason, attempt=attempt, sleeping=round(delay, 1))
        time.sleep(delay)


zoho_sync_client = ZohoSyncClient()
