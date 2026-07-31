"""Activity module — data access (append + read; never update/delete)."""

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.model import ActivityLog
from app.modules.activity.schema import ActivityListFilters


async def insert(db: AsyncSession, values: dict) -> ActivityLog:
    row = ActivityLog(**values)
    db.add(row)
    await db.flush()
    return row


def _apply_filters(query: Select, f: ActivityListFilters) -> Select:
    if f.action:
        query = query.where(ActivityLog.action == f.action)
    if f.actor_id is not None:
        query = query.where(ActivityLog.actor_id == f.actor_id)
    if f.subject_type:
        query = query.where(ActivityLog.subject_type == f.subject_type)
    if f.subject_id:
        query = query.where(ActivityLog.subject_id == f.subject_id)
    if f.status:
        query = query.where(ActivityLog.status == f.status)
    if f.since:
        query = query.where(ActivityLog.created_at >= f.since)
    if f.until:
        query = query.where(ActivityLog.created_at <= f.until)
    return query


async def list_activity(db: AsyncSession, f: ActivityListFilters) -> tuple[list[ActivityLog], int]:
    query = _apply_filters(select(ActivityLog), f)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(ActivityLog.created_at.desc())
    query = query.offset((f.page - 1) * f.page_size).limit(f.page_size)
    rows = (await db.scalars(query)).all()
    return list(rows), total


async def get_by_uuid(db: AsyncSession, activity_id) -> ActivityLog | None:
    return await db.scalar(select(ActivityLog).where(ActivityLog.activity_id == activity_id))
