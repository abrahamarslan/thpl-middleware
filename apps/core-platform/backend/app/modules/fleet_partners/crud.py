"""Fleet-partner data access — simple queries only."""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_partners.model import FleetPartner


def _base_query(include_deleted: bool = False) -> Select:
    query = select(FleetPartner)
    if include_deleted:
        query = query.execution_options(include_deleted=True)
    return query


async def get_by_id(db: AsyncSession, partner_id: int, *, include_deleted: bool = False) -> FleetPartner | None:
    return await db.scalar(_base_query(include_deleted).where(FleetPartner.id == partner_id))


async def get_by_code(db: AsyncSession, code: str) -> FleetPartner | None:
    return await db.scalar(_base_query().where(FleetPartner.code == code))


async def list_partners(
    db: AsyncSession,
    *,
    entity_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[FleetPartner]:
    stmt = _base_query().order_by(FleetPartner.name)
    if entity_type:
        stmt = stmt.where(FleetPartner.entity_type == entity_type)
    if status:
        stmt = stmt.where(FleetPartner.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(FleetPartner.name.ilike(like) | FleetPartner.code.ilike(like))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())
