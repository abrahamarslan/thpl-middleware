"""Data access for zoho_taxes (crud layer — no business logic)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.taxes.model import ZohoTax


async def list_all(
    db: AsyncSession, *, specific_type: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoTax]:
    stmt = select(ZohoTax).order_by(ZohoTax.tax_name)
    if specific_type:
        stmt = stmt.where(ZohoTax.tax_specific_type == specific_type)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def get_by_ref(db: AsyncSession, ref: str) -> ZohoTax | None:
    """Local id or Zoho id."""
    conditions = [ZohoTax.zoho_id == ref]
    if ref.isdigit():
        conditions.append(ZohoTax.id == int(ref))
    return await db.scalar(select(ZohoTax).where(or_(*conditions)).limit(1))
