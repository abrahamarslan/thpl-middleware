"""Data access for zoho_currencies (crud layer — no business logic)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho_currencies.model import ZohoCurrency


async def list_all(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[ZohoCurrency]:
    stmt = (
        select(ZohoCurrency)
        .order_by(ZohoCurrency.is_base_currency.desc().nulls_last(), ZohoCurrency.currency_code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list((await db.scalars(stmt)).all())


async def get_by_ref(db: AsyncSession, ref: str) -> ZohoCurrency | None:
    """Local id, Zoho id or ISO code (``INR``)."""
    conditions = [ZohoCurrency.zoho_id == ref, ZohoCurrency.currency_code == ref.upper()]
    if ref.isdigit():
        conditions.append(ZohoCurrency.id == int(ref))
    return await db.scalar(select(ZohoCurrency).where(or_(*conditions)).limit(1))
