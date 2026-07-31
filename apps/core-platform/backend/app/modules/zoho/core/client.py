"""Async Zoho Books client — the single entry point for all Zoho calls.

Request lifecycle (mirrors the previous PHP ZohoApiService, Python-native):

    circuit breaker check
      -> rate limiter slot
        -> valid token (ZohoTokenManager — never expired)
          -> HTTP call with X-Request-Id propagation
            -> 401?  invalidate token, retry once with fresh token
            -> 429?  honour Retry-After, retry with backoff
            -> 5xx / network?  retry with exponential backoff
          -> parse envelope {code, message, <resource>} -> ZohoResponse
        -> breaker.record_success / record_failure (infra errors only)

Business errors (Zoho code != 0, HTTP 4xx other than 401/429) are raised as
typed exceptions and do NOT trip the breaker — a bad payload is our fault,
not a Zoho outage.
"""

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog

from app.core.conf import settings
from app.modules.zoho.core.circuit_breaker import zoho_circuit_breaker
from app.modules.zoho.core.exceptions import (
    ZohoApiError,
    ZohoNotFoundError,
    ZohoRateLimitedError,
    ZohoValidationError,
)
from app.modules.zoho.core.rate_limiter import zoho_rate_limiter
from app.modules.zoho.core.schemas import ZohoResponse
from app.modules.zoho.core.token_manager import zoho_token_manager

logger = structlog.get_logger("app.zoho.client")

_MAX_ATTEMPTS = 4          # total tries per request (1 + 3 retries)
_BACKOFF_BASE = 1.5        # seconds; exponential: 1.5, 3, 6 ...
_BACKOFF_MAX = 30.0


def _endpoint_group(path: str) -> str:
    """Circuit-breaker key: first path segment ('/contacts/123' -> 'contacts')."""
    return path.strip("/").split("/", 1)[0] or "root"


class ZohoClient:
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            base_url=settings.ZOHO_API_BASE_URL,
            timeout=settings.ZOHO_TIMEOUT_SECONDS,
        )

    # ── Verb helpers ─────────────────────────────────────────────────────────

    async def get(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return await self.request("POST", path, json=json, params=params)

    async def put(self, path: str, *, json: dict | None = None, params: dict | None = None) -> ZohoResponse:
        return await self.request("PUT", path, json=json, params=params)

    async def delete(self, path: str, *, params: dict | None = None) -> ZohoResponse:
        return await self.request("DELETE", path, params=params)

    # ── Pagination ───────────────────────────────────────────────────────────

    async def paginate(
        self,
        path: str,
        *,
        params: dict | None = None,
        per_page: int = 200,
        max_pages: int | None = None,
    ) -> AsyncIterator[ZohoResponse]:
        """Iterate every page of a list endpoint via page_context.has_more_page.

        Usage:
            async for page in zoho_client.paginate("/contacts"):
                for contact in page.data: ...
        """
        page = 1
        while True:
            response = await self.get(path, params={**(params or {}), "page": page, "per_page": per_page})
            yield response
            ctx = response.page_context
            if ctx is None or not ctx.has_more_page:
                return
            page += 1
            if max_pages is not None and page > max_pages:
                logger.warning("zoho_paginate_max_pages", path=path, max_pages=max_pages)
                return

    # ── Core request ─────────────────────────────────────────────────────────

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> ZohoResponse:
        group = _endpoint_group(path)
        await zoho_circuit_breaker.check(group)

        request_id = structlog.contextvars.get_contextvars().get("request_id") or f"zoho-{uuid.uuid4().hex[:12]}"
        query = {"organization_id": settings.ZOHO_ORGANIZATION_ID, **(params or {})}

        token_retried = False
        attempt = 0
        while True:
            attempt += 1
            async with zoho_rate_limiter:
                token = await zoho_token_manager.get_token()
                started = time.perf_counter()
                try:
                    resp = await self._http.request(
                        method,
                        path,
                        params=query,
                        json=json,
                        headers={
                            "Authorization": f"Zoho-oauthtoken {token}",
                            "X-Request-Id": request_id,
                            "Accept": "application/json",
                        },
                    )
                except httpx.TransportError as e:
                    await zoho_circuit_breaker.record_failure(group)
                    if attempt >= _MAX_ATTEMPTS:
                        raise ZohoApiError(f"Zoho transport error after {attempt} attempts: {e}") from e
                    await self._sleep_backoff(attempt, reason="transport_error", path=path)
                    continue

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "zoho_api_call",
                method=method, path=path, status=resp.status_code,
                duration_ms=duration_ms, attempt=attempt, zoho_request_id=request_id,
            )

            # --- 401: token revoked/expired server-side. Invalidate + retry ONCE.
            if resp.status_code == 401:
                await zoho_token_manager.invalidate()
                if token_retried:
                    await zoho_circuit_breaker.record_failure(group)
                    raise ZohoApiError("Zoho rejected a freshly refreshed token (401)", http_status=401)
                token_retried = True
                continue

            # --- 429: rate limited. Honour Retry-After, retry with backoff.
            if resp.status_code == 429:
                await zoho_circuit_breaker.record_failure(group)
                if attempt >= _MAX_ATTEMPTS:
                    raise ZohoRateLimitedError("Zoho rate limit exceeded; retries exhausted", http_status=429)
                retry_after = float(resp.headers.get("Retry-After", 0)) or None
                await self._sleep_backoff(attempt, fixed=retry_after, reason="429", path=path)
                continue

            # --- 5xx: Zoho-side failure. Retry with backoff.
            if resp.status_code >= 500:
                await zoho_circuit_breaker.record_failure(group)
                if attempt >= _MAX_ATTEMPTS:
                    raise ZohoApiError(
                        f"Zoho server error {resp.status_code}; retries exhausted",
                        http_status=resp.status_code,
                        data={"body": resp.text[:500]},
                    )
                await self._sleep_backoff(attempt, reason=f"http_{resp.status_code}", path=path)
                continue

            return await self._finalise(
                resp, group=group, method=method, path=path,
                request_id=request_id, duration=duration_ms / 1000.0,
            )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _finalise(
        self, resp: httpx.Response, *, group: str, method: str, path: str,
        request_id: str, duration: float = 0.0,
    ) -> ZohoResponse:
        try:
            payload: dict[str, Any] = resp.json()
        except ValueError:
            payload = {"code": -1, "message": resp.text[:500]}

        response = ZohoResponse.from_payload(request_id=request_id, http_status=resp.status_code, payload=payload)

        if response.ok:
            # Duration feeds the breaker's slow-call rate detection.
            await zoho_circuit_breaker.record_success(group, duration=duration)
            return response

        # Business errors — do not trip the breaker
        logger.warning(
            "zoho_api_error",
            method=method, path=path, status=resp.status_code,
            zoho_code=response.zoho_code, zoho_message=response.message,
        )
        if resp.status_code == 404 or response.zoho_code == 1002:
            raise ZohoNotFoundError(response.message or "Zoho resource not found",
                                    zoho_code=response.zoho_code, http_status=resp.status_code)
        if resp.status_code == 400:
            raise ZohoValidationError(response.message or "Zoho rejected the request",
                                      zoho_code=response.zoho_code, http_status=resp.status_code)
        raise ZohoApiError(response.message or f"Zoho API error (code {response.zoho_code})",
                           zoho_code=response.zoho_code, http_status=resp.status_code)

    async def _sleep_backoff(self, attempt: int, *, fixed: float | None = None, reason: str = "", path: str = "") -> None:
        import asyncio

        delay = min(fixed if fixed is not None else _BACKOFF_BASE * (2 ** (attempt - 1)), _BACKOFF_MAX)
        logger.warning("zoho_retry", path=path, reason=reason, attempt=attempt, sleeping=round(delay, 1))
        await asyncio.sleep(delay)

    async def aclose(self) -> None:
        await self._http.aclose()


zoho_client = ZohoClient()
