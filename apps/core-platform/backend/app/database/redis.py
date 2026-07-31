"""Async Redis client (cache, distributed locks, Zoho token store)."""

import redis.asyncio as aioredis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from typing import AsyncGenerator

from app.core.conf import settings

# Enterprise connection settings:
# - socket_timeout & connect_timeout: Prevent hanging on network partitions
# - health_check_interval: Actively evict dead connections
# - retry: Transparently retry transient failures
redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    decode_responses=True,
    socket_timeout=5.0,
    socket_connect_timeout=2.0,
    health_check_interval=30,
    retry=Retry(ExponentialBackoff(), 3),
    retry_on_timeout=True,
)

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI Dependency for route-level Redis injection."""
    yield redis_client

async def close_redis() -> None:
    await redis_client.aclose()
