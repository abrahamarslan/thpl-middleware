"""Hub data access — simple queries only (business rules live in service)."""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hubs.model import Hub


def _base_query(include_deleted: bool = False) -> Select:
    query = select(Hub)
    if include_deleted:
        query = query.execution_options(include_deleted=True)
    return query


async def get_by_id(db: AsyncSession, hub_id: int, *, include_deleted: bool = False) -> Hub | None:
    return await db.scalar(_base_query(include_deleted).where(Hub.id == hub_id))


async def get_by_code(db: AsyncSession, code: str) -> Hub | None:
    return await db.scalar(_base_query().where(Hub.code == code))


async def list_hubs(
    db: AsyncSession,
    *,
    hub_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[Hub]:
    stmt = _base_query().order_by(Hub.name)
    if hub_type:
        stmt = stmt.where(Hub.hub_type == hub_type)
    if status:
        stmt = stmt.where(Hub.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Hub.name.ilike(like) | Hub.code.ilike(like))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())
