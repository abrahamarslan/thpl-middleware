"""Operator API data access (SQL only; no business rules)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.zoho.control.models import ZohoRetentionPolicy, ZohoSyncEvent, ZohoSyncRun


async def list_runs(
    db: AsyncSession,
    *,
    module: str | None = None,
    lane: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[ZohoSyncRun]:
    stmt = select(ZohoSyncRun).options(
        load_only(
            ZohoSyncRun.id, ZohoSyncRun.module, ZohoSyncRun.lane, ZohoSyncRun.mode,
            ZohoSyncRun.trigger, ZohoSyncRun.status, ZohoSyncRun.started_at,
            ZohoSyncRun.finished_at, ZohoSyncRun.duration_ms, ZohoSyncRun.listed,
            ZohoSyncRun.created, ZohoSyncRun.updated, ZohoSyncRun.errors,
            ZohoSyncRun.stop_reason, ZohoSyncRun.error_category,
        )
    )
    if module:
        stmt = stmt.where(ZohoSyncRun.module == module)
    if lane:
        stmt = stmt.where(ZohoSyncRun.lane == lane)
    if status:
        stmt = stmt.where(ZohoSyncRun.status == status)
    stmt = stmt.order_by(ZohoSyncRun.started_at.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


async def get_run(db: AsyncSession, run_id: uuid.UUID) -> ZohoSyncRun | None:
    return await db.get(ZohoSyncRun, run_id)


async def record_events(
    db: AsyncSession,
    *,
    module: str,
    local_id: int | None = None,
    zoho_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[ZohoSyncEvent]:
    stmt = select(ZohoSyncEvent).where(ZohoSyncEvent.module == module)
    if local_id is not None:
        stmt = stmt.where(ZohoSyncEvent.local_id == local_id)
    if zoho_id is not None:
        stmt = stmt.where(ZohoSyncEvent.zoho_id == zoho_id)
    if event_type:
        stmt = stmt.where(ZohoSyncEvent.event_type == event_type)
    stmt = stmt.order_by(ZohoSyncEvent.occurred_at.desc(), ZohoSyncEvent.id.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


async def list_policies(db: AsyncSession) -> list[ZohoRetentionPolicy]:
    stmt = select(ZohoRetentionPolicy).order_by(
        ZohoRetentionPolicy.table_name, ZohoRetentionPolicy.module, ZohoRetentionPolicy.event_class
    )
    return list((await db.scalars(stmt)).all())


async def get_policy(db: AsyncSession, policy_id: int) -> ZohoRetentionPolicy | None:
    return await db.get(ZohoRetentionPolicy, policy_id)
