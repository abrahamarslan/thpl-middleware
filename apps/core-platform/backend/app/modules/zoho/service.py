"""Business logic for Zoho sync state (service layer).

The read-through item cache that used to live here was removed on 2026-09-18
(see api.py): reads are served from local mirror tables, never from Zoho in a
request path. What remains is the small sync-state projection the legacy
`/api/zoho/sync/{entity}` endpoint exposes; it disappears with the v1 engine
once the operator API (Phase 4) lands.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho import crud
from app.modules.zoho.schema import SyncStateOut

logger = structlog.get_logger("app.zoho.service")


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
