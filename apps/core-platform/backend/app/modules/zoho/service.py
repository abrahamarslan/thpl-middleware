"""Business logic for Zoho data (service layer).

Read-through cache strategy: the sales app needs near-real-time prices and
stock, but hammering Zoho's rate limits from 50 field reps is not viable.
Short-TTL Redis caching absorbs the read load; Celery Beat refreshes the
warm path in the background (app.tasks.zoho).

All Zoho I/O goes through app.modules.zoho.core (token refresh, rate
limiting, circuit breaker, retries are handled there).
"""

import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.redis import redis_client
from app.modules.zoho import crud
from app.modules.zoho.core import zoho_client
from app.modules.zoho.schema import SyncStateOut, ZohoItem

logger = structlog.get_logger("app.zoho.service")

_ITEMS_CACHE_KEY = "zoho:items:page:{page}"
_ITEMS_CACHE_TTL = 120  # seconds


def _to_item(i: dict) -> ZohoItem:
    return ZohoItem(
        item_id=str(i.get("item_id")),
        name=i.get("name", ""),
        rate=i.get("rate", 0.0),
        stock_on_hand=i.get("stock_on_hand"),
        sku=i.get("sku"),
        status=i.get("status"),
    )


async def list_items(page: int = 1) -> list[ZohoItem]:
    import redis.exceptions
    
    cache_key = _ITEMS_CACHE_KEY.format(page=page)
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return [ZohoItem(**i) for i in json.loads(cached)]
    except redis.exceptions.ConnectionError:
        logger.error("redis_unreachable_cache_read", key=cache_key)

    response = await zoho_client.get("/items", params={"page": page})
    items = [_to_item(i) for i in response.data or []]
    
    try:
        await redis_client.set(cache_key, json.dumps([i.model_dump() for i in items]), ex=_ITEMS_CACHE_TTL)
    except redis.exceptions.ConnectionError:
        logger.error("redis_unreachable_cache_write", key=cache_key)
        
    return items


async def get_item(item_id: str) -> ZohoItem:
    response = await zoho_client.get(f"/items/{item_id}")
    return _to_item(response.data or {})


async def get_sync_status(db: AsyncSession, entity: str) -> SyncStateOut | None:
    state = await crud.get_sync_state(db, entity)
    if state is None:
        return None
    return SyncStateOut(
        entity=state.entity,
        status=state.status,
        last_synced_at=state.last_synced_at.isoformat() if state.last_synced_at else None,
        detail=state.detail,
    )
