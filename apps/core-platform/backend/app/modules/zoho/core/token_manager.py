"""Zoho OAuth2 token manager — the "never see an expired token" layer.

Zoho Token refresh:
  - access tokens live 60 minutes
  - max 10 access tokens per refresh token per 10 minutes ("Access Denied"
    beyond that) -> refreshes MUST be coordinated, never stampeded
  - max 15 active access tokens per refresh token -> mint one, share it
  - refresh tokens never expire unless revoked

Strategy:
  1. The access token is cached in Redis with TTL = expires_in - margin
     (default 120 s), so a cached token is always comfortably valid.
  2. Refresh is single-flight: one worker takes a Redis NX lock and refreshes;
     everyone else polls the cache. N uvicorn workers + M celery workers
     share ONE token.
  3. A Redis counter guards Zoho's 10-per-10-min refresh throttle and fails
     loudly *before* Zoho locks us out.
  4. If Zoho still returns 401 (token revoked server-side), the client calls
     `invalidate()` and retries once with a freshly minted token.
"""

import asyncio

import httpx
import structlog

from app.core.conf import settings
from app.database.redis import redis_client
from app.database.db import async_session_factory
from app.modules.system.service import system_settings_service
from app.modules.system.model import SettingContext
from app.modules.zoho.core.exceptions import ZohoAuthError

logger = structlog.get_logger("app.zoho.token")

TOKEN_KEY = "zoho:access_token"
REFRESH_TOKEN_KEY = "zoho:refresh_token"
LOCK_KEY = "zoho:token_refresh_lock"
THROTTLE_KEY = "zoho:token_refresh_count"

_LOCK_TTL = 30          # seconds a refresh may hold the lock
_WAIT_STEP = 0.25       # poll interval while another worker refreshes
_WAIT_MAX = 20.0        # max seconds to wait for the lock holder
_THROTTLE_WINDOW = 600  # Zoho: 10 refreshes / 10 minutes
_THROTTLE_LIMIT = 8     # stay under Zoho's 10 to keep headroom
_PERSISTENT_KEY = "zoho_refresh_token"


class ZohoTokenManager:
    async def get_token(self) -> str:
        """Return a valid access token, refreshing (single-flight) if needed."""
        token = await redis_client.get(TOKEN_KEY)
        if token:
            return token

        got_lock = await redis_client.set(LOCK_KEY, "1", nx=True, ex=_LOCK_TTL)
        if not got_lock:
            return await self._wait_for_refresh()

        try:
            # Re-check: the previous lock holder may have just refreshed
            token = await redis_client.get(TOKEN_KEY)
            if token:
                return token
            return await self._refresh()
        finally:
            await redis_client.delete(LOCK_KEY)

    async def invalidate(self) -> None:
        """Drop the cached token (called on a 401 from Zoho)."""
        await redis_client.delete(TOKEN_KEY)
        logger.warning("zoho_token_invalidated")

    async def get_refresh_token(self) -> str | None:
        """Get the refresh token from Redis, DB, or env (in that order)."""
        # 1. Try Redis
        rt = await redis_client.get(REFRESH_TOKEN_KEY)
        if rt:
            return rt

        # 2. Try DB (if enabled)
        if settings.ZOHO_TOKEN_PERSISTENCE_ENABLED:
            try:
                async with async_session_factory() as db:
                    # Using the hierarchical settings service
                    rt = await system_settings_service.get_setting(
                        db, _PERSISTENT_KEY, SettingContext.GLOBAL
                    )
                    
                    if rt:
                        # Backfill Redis
                        await redis_client.set(REFRESH_TOKEN_KEY, rt)
                        return rt
            except Exception as e:
                logger.error("zoho_token_db_read_error", error=str(e))

        # 3. Fallback to settings
        if settings.ZOHO_REFRESH_TOKEN:
            return settings.ZOHO_REFRESH_TOKEN

        return None

    async def store_tokens(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        """Store new tokens (called during OAuth callback)."""
        ttl = max(expires_in - settings.ZOHO_TOKEN_REFRESH_MARGIN, 60)
        
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.set(TOKEN_KEY, access_token, ex=ttl)
            if refresh_token:
                pipe.set(REFRESH_TOKEN_KEY, refresh_token)
            await pipe.execute()
            
        if refresh_token:
            if settings.ZOHO_TOKEN_PERSISTENCE_ENABLED:
                try:
                    async with async_session_factory() as db:
                        await system_settings_service.set_setting(
                            db, 
                            key=_PERSISTENT_KEY, 
                            value=refresh_token,
                            updated_by="system",
                            context=SettingContext.GLOBAL
                        )
                        await db.commit()
                except Exception as e:
                    logger.error("zoho_token_db_write_error", error=str(e))
        
        logger.info("zoho_tokens_stored", cached_ttl=ttl)

    async def clear_tokens(self) -> None:
        """Clear tokens from cache and optionally DB (called during revoke)."""
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.delete(TOKEN_KEY)
            pipe.delete(REFRESH_TOKEN_KEY)
            await pipe.execute()
        
        if settings.ZOHO_TOKEN_PERSISTENCE_ENABLED:
            try:
                async with async_session_factory() as db:
                    await system_settings_service.delete_setting(
                        db, _PERSISTENT_KEY, SettingContext.GLOBAL
                    )
                    await db.commit()
            except Exception as e:
                logger.error("zoho_token_db_delete_error", error=str(e))

    async def _wait_for_refresh(self) -> str:
        waited = 0.0
        while waited < _WAIT_MAX:
            await asyncio.sleep(_WAIT_STEP)
            waited += _WAIT_STEP
            token = await redis_client.get(TOKEN_KEY)
            if token:
                return token
        raise ZohoAuthError("Timed out waiting for Zoho token refresh by another worker")

    async def _check_refresh_throttle(self) -> None:
        count = await redis_client.incr(THROTTLE_KEY)
        if count == 1:
            await redis_client.expire(THROTTLE_KEY, _THROTTLE_WINDOW)
        if count > _THROTTLE_LIMIT:
            ttl = await redis_client.ttl(THROTTLE_KEY)
            logger.error("zoho_refresh_throttle_hit", count=count, window_resets_in=ttl)
            raise ZohoAuthError(
                f"Zoho token refresh throttle reached ({count} in 10 min); "
                f"window resets in {ttl}s. This indicates a token-caching bug."
            )

    async def _refresh(self) -> str:
        refresh_token = await self.get_refresh_token()
        if not refresh_token:
            raise ZohoAuthError("No Zoho refresh token available")

        await self._check_refresh_throttle()
        logger.info("zoho_token_refresh_start")

        async with httpx.AsyncClient(timeout=settings.ZOHO_TIMEOUT_SECONDS) as http:
            resp = await http.post(
                f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token",
                params={
                    "refresh_token": refresh_token,
                    "client_id": settings.ZOHO_CLIENT_ID,
                    "client_secret": settings.ZOHO_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
            )

        if resp.status_code != 200:
            logger.error("zoho_token_refresh_failed", status=resp.status_code, body=resp.text[:500])
            raise ZohoAuthError(
                "Zoho token refresh failed — check client credentials / refresh token",
                http_status=resp.status_code,
            )

        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise ZohoAuthError(f"Zoho token refresh error: {payload.get('error', 'no access_token in response')}")

        expires_in = int(payload.get("expires_in", 3600))
        new_refresh = payload.get("refresh_token")
        
        await self.store_tokens(token, new_refresh or refresh_token, expires_in)
        
        logger.info("zoho_token_refresh_ok", expires_in=expires_in)
        return token


zoho_token_manager = ZohoTokenManager()

