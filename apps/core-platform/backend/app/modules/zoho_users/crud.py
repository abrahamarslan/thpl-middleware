"""Data access for zoho_users (crud layer — no business logic)."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho_users.model import ZohoUser


async def list_all(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoUser]:
    stmt = select(ZohoUser).order_by(ZohoUser.name)
    if status:
        stmt = stmt.where(ZohoUser.zoho_status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def get_by_ref(db: AsyncSession, ref: str) -> ZohoUser | None:
    """Local id, Zoho id or email."""
    conditions = [ZohoUser.zoho_id == ref, func.lower(ZohoUser.email) == ref.lower()]
    if ref.isdigit():
        conditions.append(ZohoUser.id == int(ref))
    return await db.scalar(select(ZohoUser).where(or_(*conditions)).limit(1))
