"""Data access for zoho_locations (crud layer — no business logic)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.locations.model import ZohoLocation


async def list_all(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoLocation]:
    stmt = select(ZohoLocation).order_by(ZohoLocation.is_primary.desc().nulls_last(), ZohoLocation.location_name)
    if status:
        stmt = stmt.where(ZohoLocation.zoho_status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def get_by_ref(db: AsyncSession, ref: str) -> ZohoLocation | None:
    """Local id or Zoho id."""
    conditions = [ZohoLocation.zoho_id == ref]
    if ref.isdigit():
        conditions.append(ZohoLocation.id == int(ref))
    return await db.scalar(select(ZohoLocation).where(or_(*conditions)).limit(1))
