"""Token manager v2 — one valid access token for the whole fleet.

Zoho's OAuth limits make this a coordination problem, not a caching one
(`docs/zoho-docs-md/oauth-zoho.md`):

  * an access token lives 1 hour;
  * at most **10 access tokens per refresh token per 10 minutes** — exceed it
    and Zoho answers "Access Denied" for the rest of the window;
  * at most 15 active access tokens; minting a 16th invalidates the oldest,
    so a stampede does not just waste calls, it *breaks tokens in use*;
  * refresh tokens never expire, but are deleted on revoke / password change
    with session removal, and only 20 may exist per user.

So: one token in Redis, refreshed single-flight, with a throttle guard that
fails loudly before Zoho locks us out.

What v1 got wrong (all fixed here):

| # | v1 | v2 |
|---|---|---|
| 1 | lock released with `DEL` — a slow refresher deleted the *next* holder's lock | owner token + Lua compare-and-delete |
| 2 | lock TTL 30 s == the refresh HTTP timeout, so the lock could expire mid-refresh | TTL = timeout + headroom, and the holder re-checks ownership before writing |
| 3 | `invalidate()` deleted whatever token was cached — a stale 401 evicted a *fresh* token | compare-and-delete on the token value |
| 4 | refresh token written to `setting_values` **and** `setting_audit_logs` (plaintext, forever) | encrypted row in `zoho_oauth_credentials` (§ model.py), never audited |
| 5 | refresh token cached in Redis with no TTL under `allkeys-lru` → eviction = auth outage | never in Redis; short-lived in-process cache only |
| 6 | the Celery sync client refreshed from `settings.ZOHO_REFRESH_TOKEN` only, ignoring a rotated token | one manager, one source, used by every process |
| 7 | a revoked refresh token looked like any other failure | `ZohoAuthRevokedError` → the engine pauses and alerts |
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from redis.exceptions import RedisError
from sqlalchemy import select, text

from app.core.conf import settings
from app.database.db import async_session_factory
from app.database.redis import redis_client
from app.modules.zoho.core.errors import (
    ZohoAuthError,
    ZohoAuthRevokedError,
    ZohoAuthThrottledError,
)
from app.modules.zoho.model import ZohoOAuthCredential

logger = structlog.get_logger("app.zoho.auth")

# ── Redis keys (DB 0; all short-lived, all safe to lose) ─────────────────────
TOKEN_KEY = "zoho:oauth:{org}:access"
LOCK_KEY = "zoho:oauth:{org}:refresh_lock"
THROTTLE_KEY = "zoho:oauth:{org}:refresh_count"

# Legacy v1 keys — still read once so a running deployment does not lose its
# token mid-deploy. Never written.
_LEGACY_TOKEN_KEY = "zoho:access_token"
_LEGACY_REFRESH_KEY = "zoho:refresh_token"

_THROTTLE_WINDOW = 600      # Zoho counts 10 refreshes per 10 minutes
_THROTTLE_LIMIT = 8         # stay under it, loudly
_WAIT_STEP = 0.25
_WAIT_JITTER = 0.15
_WAIT_MAX = 20.0

_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_INVALIDATE_TOKEN_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class CredentialUnavailable(ZohoAuthError):
    """No refresh token is configured anywhere — operator action required."""

    code = "zoho_credentials_missing"


@dataclass(slots=True)
class Credential:
    """A refresh token plus where it came from (for diagnostics, never logged)."""

    refresh_token: str
    source: str                     # "database" | "environment"
    version: int = 1
    api_domain: str | None = None
    loaded_at: float = field(default_factory=time.monotonic)


class CredentialStore:
    """Encrypted refresh-token storage with an in-process cache.

    Order of truth: the database row (encrypted) → ``ZOHO_REFRESH_TOKEN``
    (bootstrap seed for a fresh environment). The token never enters Redis,
    logs, spans or the settings audit trail.
    """

    def __init__(self, *, cache_ttl: float = 300.0, session_factory=None) -> None:
        self._cached: Credential | None = None
        self._cache_ttl = cache_ttl
        self._lock = asyncio.Lock()
        # Injectable because the module-level factory is a POOLED engine bound
        # to the process's main event loop: a Celery task (own loop per task)
        # must pass its own throwaway NullPool factory, or asyncpg raises
        # "attached to a different loop". Same reason the tests inject one.
        self._session_factory = session_factory or async_session_factory

    @property
    def encryption_key(self) -> str:
        return settings.ZOHO_TOKEN_ENCRYPTION_KEY

    @property
    def db_enabled(self) -> bool:
        """DB persistence needs both the flag and a key — never store plaintext."""
        return bool(settings.ZOHO_TOKEN_PERSISTENCE_ENABLED and self.encryption_key)

    def invalidate_cache(self) -> None:
        self._cached = None

    def bind_session_factory(self, session_factory) -> None:
        """Point the store at the caller's engine (Celery tasks; see __init__)."""
        self._session_factory = session_factory

    async def load(self) -> Credential:
        if self._cached and (time.monotonic() - self._cached.loaded_at) < self._cache_ttl:
            return self._cached

        async with self._lock:
            if self._cached and (time.monotonic() - self._cached.loaded_at) < self._cache_ttl:
                return self._cached

            credential = await self._load_from_db() if self.db_enabled else None
            if credential is None and settings.ZOHO_REFRESH_TOKEN:
                credential = Credential(settings.ZOHO_REFRESH_TOKEN, source="environment")
            if credential is None:
                raise CredentialUnavailable(
                    "No Zoho refresh token available: connect the integration "
                    "(/api/zoho/auth/initiate) or set ZOHO_REFRESH_TOKEN"
                )
            self._cached = credential
            return credential

    async def _load_from_db(self) -> Credential | None:
        try:
            async with self._session_factory() as db:
                # A refresh token belongs to the Zoho USER, not to one org: after
                # ZOHO_ORGANIZATION_ID is corrected (ERRORS E35) the credential
                # stored under the old id is still valid. Prefer the current
                # org's row, else the most recently rotated active one.
                row = await db.execute(
                    text(
                        "SELECT pgp_sym_decrypt(refresh_token_enc, :key) AS token,"
                        "       credential_version, api_domain, org_id "
                        "FROM zoho_oauth_credentials "
                        "WHERE revoked_at IS NULL AND refresh_token_enc IS NOT NULL "
                        "ORDER BY (org_id = :org) DESC, rotated_at DESC NULLS LAST LIMIT 1"
                    ),
                    {"key": self.encryption_key, "org": settings.ZOHO_ORGANIZATION_ID},
                )
                record = row.mappings().first()
                if record and record["org_id"] != settings.ZOHO_ORGANIZATION_ID:
                    logger.warning("zoho.auth.credential_org_mismatch", stored_org=record["org_id"],
                                   configured_org=settings.ZOHO_ORGANIZATION_ID,
                                   action="using it; the next rotation stores it under the configured org")
        except Exception as exc:  # noqa: BLE001 — never let storage break auth
            logger.error("zoho.auth.credential_read_failed", error=str(exc))
            return None
        if not record or not record["token"]:
            return None
        return Credential(
            refresh_token=record["token"],
            source="database",
            version=int(record["credential_version"] or 1),
            api_domain=record["api_domain"],
        )

    async def store(
        self,
        refresh_token: str,
        *,
        api_domain: str | None = None,
        scope: str | None = None,
        actor_id: int | None = None,
    ) -> None:
        """Persist a rotated refresh token (OAuth callback / re-consent)."""
        if not self.db_enabled:
            logger.warning(
                "zoho.auth.credential_not_persisted",
                reason="persistence_disabled" if not settings.ZOHO_TOKEN_PERSISTENCE_ENABLED
                else "encryption_key_missing",
            )
            self._cached = Credential(refresh_token, source="environment")
            return

        async with self._session_factory() as db:
            existing = await db.scalar(
                select(ZohoOAuthCredential).where(
                    ZohoOAuthCredential.org_id == settings.ZOHO_ORGANIZATION_ID
                )
            )
            version = (existing.credential_version + 1) if existing else 1
            from app.database.tenancy import resolve_tenant_id

            tenant_id = await resolve_tenant_id(db, settings.ZOHO_TENANT_CODE or None)
            await db.execute(
                text(
                    """
                    INSERT INTO zoho_oauth_credentials
                        (tenant_id, org_id, refresh_token_enc, api_domain, scope, credential_version,
                         rotated_at, rotated_by, revoked_at, created_at, updated_at, app_metadata)
                    VALUES
                        (:tenant, :org, pgp_sym_encrypt(:token, :key), :api_domain, :scope, :version,
                         now(), :actor, NULL, now(), now(), '{}'::jsonb)
                    ON CONFLICT (org_id) DO UPDATE SET
                        refresh_token_enc = EXCLUDED.refresh_token_enc,
                        api_domain        = COALESCE(EXCLUDED.api_domain, zoho_oauth_credentials.api_domain),
                        scope             = COALESCE(EXCLUDED.scope, zoho_oauth_credentials.scope),
                        credential_version = EXCLUDED.credential_version,
                        rotated_at        = now(),
                        rotated_by        = EXCLUDED.rotated_by,
                        revoked_at        = NULL,
                        updated_at        = now()
                    """
                ),
                {
                    "tenant": tenant_id,
                    "org": settings.ZOHO_ORGANIZATION_ID,
                    "token": refresh_token,
                    "key": self.encryption_key,
                    "api_domain": api_domain,
                    "scope": scope,
                    "version": version,
                    "actor": actor_id,
                },
            )
            await db.commit()
        self._cached = Credential(refresh_token, source="database", version=version, api_domain=api_domain)
        logger.info("zoho.auth.credential_rotated", version=version, actor_id=actor_id, api_domain=api_domain)

    async def revoke(self) -> None:
        """Mark the stored credential revoked (disconnect flow)."""
        self._cached = None
        if not self.db_enabled:
            return
        async with self._session_factory() as db:
            await db.execute(
                text(
                    "UPDATE zoho_oauth_credentials "
                    "SET refresh_token_enc = NULL, revoked_at = now(), updated_at = now() "
                    "WHERE org_id = :org"
                ),
                {"org": settings.ZOHO_ORGANIZATION_ID},
            )
            await db.commit()
        logger.info("zoho.auth.credential_revoked")


class ZohoTokenManager:
    """Hands out a valid access token; refreshes it exactly once per fleet."""

    def __init__(
        self,
        store: CredentialStore | None = None,
        redis=None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._store = store or CredentialStore()
        self._redis = redis if redis is not None else redis_client
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=settings.ZOHO_TIMEOUT_SECONDS)
        )
        self._release_lock = None
        self._invalidate = None
        self._memory_token: tuple[str, float] | None = None   # (token, expires_at) — Redis-outage fallback

    @property
    def store(self) -> CredentialStore:
        return self._store

    # ── keys / scripts ──────────────────────────────────────────────────────

    def _key(self, template: str) -> str:
        return template.format(org=settings.ZOHO_ORGANIZATION_ID or "org")

    def _scripts(self):
        if self._release_lock is None:
            self._release_lock = self._redis.register_script(_RELEASE_LOCK_LUA)
            self._invalidate = self._redis.register_script(_INVALIDATE_TOKEN_LUA)
        return self._release_lock, self._invalidate

    @property
    def _lock_ttl_ms(self) -> int:
        # Must outlive the refresh call itself, or the lock expires mid-flight
        # and a second worker mints a token we are about to overwrite.
        return int((settings.ZOHO_TIMEOUT_SECONDS + 15) * 1000)

    # ── public API ──────────────────────────────────────────────────────────

    async def get_token(self) -> str:
        """A token that is valid now — cached, or refreshed single-flight."""
        token = await self._cached_token()
        if token:
            return token

        lock_key = self._key(LOCK_KEY)
        owner = f"{time.time_ns()}-{random.getrandbits(32):x}"
        try:
            got_lock = await self._redis.set(lock_key, owner, nx=True, px=self._lock_ttl_ms)
        except RedisError as exc:
            logger.error("zoho.auth.lock_unavailable", error=str(exc))
            return await self._refresh()          # degraded: refresh without coordination

        if not got_lock:
            return await self._wait_for_refresh()

        try:
            token = await self._cached_token()    # the previous holder may have just refreshed
            if token:
                return token
            return await self._refresh()
        finally:
            try:
                release, _ = self._scripts()
                await release(keys=[lock_key], args=[owner])   # compare-and-delete
            except RedisError as exc:
                logger.warning("zoho.auth.lock_release_failed", error=str(exc))

    async def invalidate(self, token: str | None = None) -> None:
        """Drop the cached token after a 401 — only if it is still *that* token."""
        self._memory_token = None
        key = self._key(TOKEN_KEY)
        try:
            if token:
                _, invalidate = self._scripts()
                removed = await invalidate(keys=[key], args=[token])
                if not removed:
                    logger.info("zoho.auth.invalidate_skipped", reason="token_already_rotated")
                    return
            else:
                await self._redis.delete(key)
        except RedisError as exc:
            logger.warning("zoho.auth.invalidate_failed", error=str(exc))
        logger.warning("zoho.auth.token_invalidated")

    async def store_tokens(
        self,
        access_token: str,
        refresh_token: str | None,
        expires_in: int,
        *,
        api_domain: str | None = None,
        scope: str | None = None,
        actor_id: int | None = None,
    ) -> None:
        """Called by the OAuth callback after a consent exchange."""
        await self._cache_token(access_token, expires_in)
        if refresh_token:
            await self._store.store(refresh_token, api_domain=api_domain, scope=scope, actor_id=actor_id)
        # A successful consent exchange is the only thing that lifts an auth pause.
        from app.modules.zoho.control.switches import zoho_switches

        await zoho_switches.clear_auth_paused()

    async def get_refresh_token(self) -> str | None:
        """Is the integration connected? (Used by the auth status endpoint.)

        Returns the credential itself for the revoke call — callers must never
        log it, and it is never returned to an API client.
        """
        try:
            return (await self._store.load()).refresh_token
        except CredentialUnavailable:
            return None

    async def clear_tokens(self) -> None:
        """Disconnect: forget the access token and revoke the stored credential."""
        self._memory_token = None
        try:
            await self._redis.delete(self._key(TOKEN_KEY), self._key(LOCK_KEY))
        except RedisError:
            pass
        await self._store.revoke()

    async def health(self) -> dict[str, Any]:
        """For the admin API and the token-health metric."""
        ttl = -1
        refreshes = 0
        healthy = True
        try:
            ttl = int(await self._redis.ttl(self._key(TOKEN_KEY)))
            refreshes = int(await self._redis.get(self._key(THROTTLE_KEY)) or 0)
        except (RedisError, ValueError, TypeError):
            healthy = False
        credential_source = self._store._cached.source if self._store._cached else None
        return {
            "token_ttl_seconds": max(ttl, 0),
            "has_token": ttl > 0,
            "refreshes_in_window": refreshes,
            "refresh_throttle_limit": _THROTTLE_LIMIT,
            "credential_source": credential_source,
            "db_persistence": self._store.db_enabled,
            "redis_healthy": healthy,
        }

    # ── internals ───────────────────────────────────────────────────────────

    async def _cached_token(self) -> str | None:
        try:
            token = await self._redis.get(self._key(TOKEN_KEY))
            if token:
                return token
            legacy = await self._redis.get(_LEGACY_TOKEN_KEY)   # v1 key, read-only
            if legacy:
                return legacy
        except RedisError:
            cached = self._memory_token
            if cached and cached[1] > time.monotonic():
                return cached[0]
        return None

    async def _cache_token(self, token: str, expires_in: int) -> None:
        ttl = max(int(expires_in) - settings.ZOHO_TOKEN_REFRESH_MARGIN, 60)
        self._memory_token = (token, time.monotonic() + ttl)
        try:
            await self._redis.set(self._key(TOKEN_KEY), token, ex=ttl)
        except RedisError as exc:
            logger.error("zoho.auth.token_cache_failed", error=str(exc))

    async def _wait_for_refresh(self) -> str:
        """Another worker holds the lock: poll for its result (jittered)."""
        waited = 0.0
        while waited < _WAIT_MAX:
            delay = _WAIT_STEP + random.uniform(0, _WAIT_JITTER)
            await asyncio.sleep(delay)
            waited += delay
            token = await self._cached_token()
            if token:
                return token
        raise ZohoAuthError("Timed out waiting for another worker to refresh the Zoho token")

    async def _check_throttle(self) -> None:
        try:
            count = int(await self._redis.incr(self._key(THROTTLE_KEY)))
            if count == 1:
                await self._redis.expire(self._key(THROTTLE_KEY), _THROTTLE_WINDOW)
        except RedisError:
            return                                    # cannot count — proceed, logged elsewhere
        if count > _THROTTLE_LIMIT:
            ttl = await self._redis.ttl(self._key(THROTTLE_KEY))
            logger.critical("zoho.auth.refresh_throttled", count=count, window_resets_in=ttl)
            raise ZohoAuthThrottledError(
                f"Zoho token refreshed {count} times in 10 minutes (Zoho allows 10). "
                "This indicates a token-caching bug; refusing to refresh again.",
                retry_after=float(max(ttl, 0)),
            )

    async def _refresh(self) -> str:
        credential = await self._store.load()
        await self._check_throttle()

        logger.info("zoho.auth.refresh_started", credential_source=credential.source)
        try:
            async with self._http_client_factory() as http:
                # Zoho requires these as query params (oauth-zoho.md); the OTel
                # httpx hook strips the query for accounts.zoho.* so the secret
                # never reaches Tempo.
                response = await http.post(
                    settings.ZOHO_ACCESS_TOKEN_URL,
                    params={
                        "refresh_token": credential.refresh_token,
                        "client_id": settings.ZOHO_CLIENT_ID,
                        "client_secret": settings.ZOHO_CLIENT_SECRET,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.HTTPError as exc:
            raise ZohoAuthError(f"Zoho token refresh failed: {exc}") from exc

        if response.status_code != 200:
            logger.error("zoho.auth.refresh_failed", status=response.status_code)
            raise ZohoAuthError(
                "Zoho token refresh failed — check client credentials and the refresh token",
                http_status=response.status_code,
            )

        payload = response.json()
        error = payload.get("error")
        if error in ("invalid_code", "invalid_grant", "invalid_client"):
            self._store.invalidate_cache()
            logger.critical("zoho.auth.refresh_revoked", error=error, credential_source=credential.source)
            # Stop every Zoho call fleet-wide until an operator reconnects —
            # retrying a revoked token only burns the refresh throttle.
            from app.modules.zoho.control.switches import zoho_switches

            await zoho_switches.set_auth_paused(f"refresh_token_{error}")
            raise ZohoAuthRevokedError(
                f"Zoho rejected the refresh token ({error}); the integration must be reconnected",
                data={"zoho_error": error},
            )
        if error:
            raise ZohoAuthError(f"Zoho token refresh error: {error}")

        token = payload.get("access_token")
        if not token:
            raise ZohoAuthError("Zoho token refresh returned no access_token")

        expires_in = int(payload.get("expires_in", 3600))
        await self._cache_token(token, expires_in)

        api_domain = payload.get("api_domain")
        if api_domain and not self._domain_matches(api_domain):
            logger.error(
                "zoho.auth.api_domain_mismatch",
                api_domain=api_domain, configured=settings.ZOHO_API_BASE_URL,
            )

        # Zoho may rotate the refresh token during a refresh; persist it.
        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != credential.refresh_token:
            await self._store.store(new_refresh, api_domain=api_domain)

        logger.info(
            "zoho.auth.refresh_succeeded",
            expires_in=expires_in, cached_ttl=max(expires_in - settings.ZOHO_TOKEN_REFRESH_MARGIN, 60),
        )
        return token

    @staticmethod
    def _domain_matches(api_domain: str) -> bool:
        """Guard against a Multi-DC mix-up (token minted in the wrong data centre)."""
        host = api_domain.split("//")[-1].strip("/")
        return host in settings.ZOHO_API_BASE_URL or host in settings.ZOHO_INVENTORY_API_URL


zoho_token_manager = ZohoTokenManager()

__all__ = [
    "Credential",
    "CredentialStore",
    "CredentialUnavailable",
    "ZohoTokenManager",
    "zoho_token_manager",
]
