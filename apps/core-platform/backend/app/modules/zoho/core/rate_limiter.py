"""Outbound rate limiter for Zoho Books.

Zoho Books enforces ~100 requests/min/org and ~10 concurrent calls.
Two layers of protection:

  1. Global per-minute budget — Redis fixed-window counter shared by ALL
     workers (API + Celery). When the window is full, `acquire()` waits for
     the next window instead of letting Zoho return 429s.
  2. Per-process concurrency cap — asyncio.Semaphore (Zoho's concurrent
     call limit divided across processes is approximated; the global
     counter is the hard guarantee).
"""

import asyncio
import time

import structlog

from app.core.conf import settings
from app.database.redis import redis_client

logger = structlog.get_logger("app.zoho.ratelimit")

_WINDOW_KEY = "zoho:rl:{window}"
_MAX_WAIT = 90.0  # give up if we'd wait longer than this


class ZohoRateLimiter:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.ZOHO_MAX_CONCURRENT_REQUESTS)

    async def __aenter__(self) -> "ZohoRateLimiter":
        await self._semaphore.acquire()
        try:
            await self._acquire_window_slot()
        except BaseException:
            self._semaphore.release()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        self._semaphore.release()

    async def _acquire_window_slot(self) -> None:
        waited = 0.0
        while True:
            window = int(time.time() // 60)
            key = _WINDOW_KEY.format(window=window)
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, 120)
            if count <= settings.ZOHO_RATE_LIMIT_PER_MINUTE:
                return

            # Window full — wait for the next minute boundary
            sleep_for = 60 - (time.time() % 60) + 0.05
            waited += sleep_for
            if waited > _MAX_WAIT:
                from app.modules.zoho.core.exceptions import ZohoRateLimitedError

                raise ZohoRateLimitedError("Local Zoho rate-limit budget exhausted; try later")
            logger.warning("zoho_rate_limit_window_full", sleeping=round(sleep_for, 1))
            await asyncio.sleep(sleep_for)


zoho_rate_limiter = ZohoRateLimiter()
