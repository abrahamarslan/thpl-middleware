"""Reading and writing ``geo.geocode_api_calls``.

Every upstream call lands here — the hits, the empties and the failures —
because the table is three things at once: the cache, the audit trail and the
spend ledger. Separating them would mean three writes and three chances to
disagree about what happened.

What is servable and what is merely recorded is decided by ``expires_at``:

* a good answer expires at the provider's licence window (Google: 30 days);
* ``ZERO_RESULTS`` expires sooner but is still cached — an address that does
  not exist today will not exist in an hour either, and paying to rediscover
  that on every retry is how a geocoding bill grows;
* a failure is written with ``expires_at`` already in the past, so it is
  visible in the audit trail and can never be served as an answer.

One index serves the lookup: ``ix_geocode_calls_cache`` on
``(tenant_id, provider, api_type, request_hash, created_at DESC)``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.enums import GeoApiType
from app.modules.geo.model import GeocodeApiCall

logger = structlog.get_logger("app.geo.geocoding.cache")

#: A "no results" answer is cached, but briefly — coverage improves.
ZERO_RESULT_CACHE_HOURS = 24


def request_hash(provider: str, api_type: GeoApiType | str, cache_params: dict[str, Any]) -> str:
    """Stable identity of a request.

    ``sort_keys`` matters: two callers building the same query with their keys
    in a different order must hash the same, or the cache never hits.
    """
    canonical = json.dumps(
        {"provider": provider, "api_type": str(getattr(api_type, "value", api_type)),
         "params": cache_params},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def lookup(
    db: AsyncSession, *, provider: str, api_type: GeoApiType, digest: str,
) -> GeocodeApiCall | None:
    """The freshest servable answer for this request, if there is one.

    Tenant scoping is automatic (``geo.geocode_api_calls`` is tenant-bound, so
    ``app/database/tenancy.py`` adds the filter). That is deliberate: a
    request hash contains the address someone searched for, and a shared cache
    would leak one tenant's address book into another's lookups.
    """
    now = dt.datetime.now(dt.UTC)
    return await db.scalar(
        select(GeocodeApiCall)
        .where(
            GeocodeApiCall.provider == provider,
            GeocodeApiCall.api_type == api_type.value,
            GeocodeApiCall.request_hash == digest,
            GeocodeApiCall.expires_at.isnot(None),
            GeocodeApiCall.expires_at > now,
        )
        .order_by(GeocodeApiCall.created_at.desc())
        .limit(1)
    )


async def record(
    db: AsyncSession, *,
    organization_id: int,
    provider: str,
    api_type: GeoApiType,
    digest: str,
    cache_params: dict[str, Any],
    payload: Any = None,
    response_status: str | None = None,
    http_status: int | None = None,
    latency_ms: int | None = None,
    cost_units: float | None = None,
    cache_days: int | None = None,
    servable: bool = True,
    empty: bool = False,
    requested_by: int | None = None,
) -> GeocodeApiCall:
    """Write one call. Returns the row so the caller can link provenance."""
    now = dt.datetime.now(dt.UTC)
    if not servable:
        expires_at = now                                   # audited, never served
    elif empty:
        expires_at = now + dt.timedelta(hours=ZERO_RESULT_CACHE_HOURS)
    else:
        expires_at = now + dt.timedelta(days=max(1, cache_days or 30))

    call = GeocodeApiCall(
        organization_id=organization_id,
        provider=provider,
        api_type=api_type.value,
        request_hash=digest,
        request_params=_scrub(cache_params),
        response_raw=payload if isinstance(payload, (dict, list)) else None,
        response_status=response_status,
        http_status=http_status,
        latency_ms=latency_ms,
        cost_units=cost_units,
        requested_by=requested_by,
        expires_at=expires_at,
    )
    db.add(call)
    await db.flush()
    return call


#: Parameter names that must never reach the stored payload.
_SECRET_KEYS = frozenset({"key", "access_token", "api_key", "token", "apikey", "authorization"})


def _scrub(params: dict[str, Any]) -> dict[str, Any]:
    """Belt and braces.

    Providers are told to keep credentials out of ``cache_params``, and this
    makes sure a future one that forgets cannot write a key into a table that
    every tenant user can read.
    """
    return {
        key: ("***" if key.lower() in _SECRET_KEYS else value)
        for key, value in (params or {}).items()
    }


async def purge_expired(db: AsyncSession, *, older_than_days: int = 0) -> int:
    """Delete payloads past their licence window.

    The reason the raw payload lives in exactly one table: this sweep clears
    every provider response in the platform, and no other table has to know
    that Google's terms say thirty days.
    """
    from sqlalchemy import delete

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=older_than_days)
    result = await db.execute(
        delete(GeocodeApiCall)
        .where(GeocodeApiCall.expires_at.isnot(None), GeocodeApiCall.expires_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    deleted = int(result.rowcount or 0)
    if deleted:
        logger.info("geo.geocoding.purged", rows=deleted, older_than_days=older_than_days)
    return deleted


__all__ = ["ZERO_RESULT_CACHE_HOURS", "lookup", "purge_expired", "record", "request_hash"]
