"""HTTP execution, and the guard rails around it.

Everything a provider must not have to think about lives here: timeouts,
retries, a token-bucket rate limit, and a circuit breaker. Written once, so a
provider added next year inherits all of it by existing.

**Fail-open, deliberately.** Redis backs the limiter and the breaker. If Redis
is down, geocoding keeps working without them — degraded protection beats an
address book that stops answering because a cache is unreachable. The Zoho
governor is fail-*closed* because exceeding Zoho's quota blocks the whole
organization; a geocoding overrun costs money, not availability, so the
trade-off is the other way round.

This is a separate client from the Zoho transport on purpose: import
contracts forbid the location hub from importing it, and the two have nothing
in common but the library.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from redis.exceptions import RedisError

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.geo.geocoding.types import (
    ProviderRejected,
    ProviderRequest,
    ProviderTransientError,
)

logger = structlog.get_logger("app.geo.geocoding.transport")

_BUCKET_KEY = "geo:rate:{provider}:{minute}"
_BREAKER_KEY = "geo:cb:{provider}"
_FAILURE_KEY = "geo:cb:{provider}:failures"

#: Status codes that mean "ask again later", not "you asked wrong".
_TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """One pooled client for every geo provider."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.GEOCODING_TIMEOUT_SECONDS,
                connect=settings.GEOCODING_CONNECT_TIMEOUT_SECONDS,
            ),
            follow_redirects=True,
            headers={"Accept": "application/json"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


@dataclass(slots=True)
class CallOutcome:
    payload: Any
    http_status: int
    latency_ms: int
    attempts: int


# ── rate limiting ───────────────────────────────────────────────────────────

async def _acquire_slot(provider: str, limit: int) -> None:
    """Fixed-window counter, one key per provider per minute.

    A fixed window can let through up to 2× the limit across a boundary. For
    a provider policy quoted per second (Nominatim) that matters, so callers
    also space requests; for a per-day billing cap it does not. The simplicity
    is worth more here than the precision of a sliding log.
    """
    if limit <= 0:
        return
    key = _BUCKET_KEY.format(provider=provider, minute=int(time.time() // 60))
    try:
        used = await redis_client.incr(key)
        if used == 1:
            await redis_client.expire(key, 120)
        if used > limit:
            raise ProviderTransientError(
                f"local rate limit for '{provider}' reached ({limit}/min); try again shortly"
            )
    except RedisError:
        logger.warning("geo.geocoding.rate_limit_unavailable", provider=provider)


# ── circuit breaker ─────────────────────────────────────────────────────────

async def _breaker_open(provider: str) -> bool:
    try:
        return bool(await redis_client.exists(_BREAKER_KEY.format(provider=provider)))
    except RedisError:
        return False


async def _record_failure(provider: str) -> None:
    """Trip after N consecutive transient failures; the key's own TTL is the
    cool-down, so nothing has to schedule a reset."""
    try:
        key = _FAILURE_KEY.format(provider=provider)
        failures = await redis_client.incr(key)
        await redis_client.expire(key, settings.GEOCODING_CB_WINDOW_SECONDS)
        if failures >= settings.GEOCODING_CB_FAILURES:
            await redis_client.set(
                _BREAKER_KEY.format(provider=provider), "open",
                ex=settings.GEOCODING_CB_RECOVERY_SECONDS,
            )
            logger.warning("geo.geocoding.circuit_open", provider=provider, failures=failures,
                           recovery_seconds=settings.GEOCODING_CB_RECOVERY_SECONDS)
    except RedisError:
        pass


async def _record_success(provider: str) -> None:
    try:
        await redis_client.delete(_FAILURE_KEY.format(provider=provider))
    except RedisError:
        pass


async def breaker_state(provider: str) -> str:
    return "open" if await _breaker_open(provider) else "closed"


async def reset_breaker(provider: str) -> None:
    try:
        await redis_client.delete(
            _BREAKER_KEY.format(provider=provider), _FAILURE_KEY.format(provider=provider),
        )
    except RedisError:
        pass


# ── execution ───────────────────────────────────────────────────────────────

async def execute(request: ProviderRequest, *, provider: str, rate_limit: int) -> CallOutcome:
    """Run one provider request with the guard rails applied.

    Raises ``ProviderTransientError`` (retryable, try the next provider) or
    ``ProviderRejected`` (the request or the account is wrong).
    """
    if await _breaker_open(provider):
        raise ProviderTransientError(f"circuit open for '{provider}'")
    await _acquire_slot(provider, rate_limit)

    client = get_client()
    started = time.perf_counter()
    last_error: Exception | None = None

    for attempt in range(1, settings.GEOCODING_MAX_ATTEMPTS + 1):
        try:
            response = await client.request(
                request.method, request.url,
                params=request.params or None,
                json=request.json_body,
                headers=request.headers or None,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = ProviderTransientError(f"{provider}: {type(exc).__name__}")
        else:
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code in _TRANSIENT_STATUS:
                last_error = ProviderTransientError(
                    f"{provider}: HTTP {response.status_code}"
                )
            elif response.status_code >= 400:
                await _record_success(provider)      # it answered; it is not down
                raise ProviderRejected(
                    f"{provider}: HTTP {response.status_code} {response.text[:200]}"
                )
            else:
                await _record_success(provider)
                return CallOutcome(
                    payload=_json(response), http_status=response.status_code,
                    latency_ms=latency_ms, attempts=attempt,
                )

        if attempt < settings.GEOCODING_MAX_ATTEMPTS:
            # Exponential backoff. No jitter: these are a handful of calls on
            # an interactive path, not a thundering herd.
            await asyncio.sleep(settings.GEOCODING_RETRY_BACKOFF_SECONDS * attempt)

    await _record_failure(provider)
    raise last_error or ProviderTransientError(f"{provider}: exhausted retries")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderRejected(
            f"provider returned {response.headers.get('content-type', 'unknown')}, not JSON"
        ) from exc


__all__ = [
    "CallOutcome",
    "breaker_state",
    "close_client",
    "execute",
    "get_client",
    "reset_breaker",
]
