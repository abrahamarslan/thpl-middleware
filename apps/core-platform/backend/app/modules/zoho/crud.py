"""Data access for Zoho sync state (crud layer — no business logic)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho.model import ZohoSyncState


async def get_sync_state(db: AsyncSession, entity: str) -> ZohoSyncState | None:
    return await db.scalar(select(ZohoSyncState).where(ZohoSyncState.entity == entity))


async def upsert_sync_state(
    db: AsyncSession, entity: str, *, status: str, detail: str | None = None
) -> ZohoSyncState:
    state = await get_sync_state(db, entity)
    if state is None:
        state = ZohoSyncState(entity=entity)
        db.add(state)
    state.status = status
    state.detail = detail
    if status == "success":
        state.last_synced_at = datetime.now(UTC)
    await db.flush()
    return state
