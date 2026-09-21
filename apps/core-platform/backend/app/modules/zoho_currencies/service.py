"""Currencies business logic — reads from the local mirror only (zero Zoho calls)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.zoho_currencies import crud
from app.modules.zoho_currencies.model import ZohoCurrency


async def list_currencies(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[ZohoCurrency]:
    return await crud.list_all(db, page=page, page_size=page_size)


async def get_currency(db: AsyncSession, ref: str) -> ZohoCurrency:
    row = await crud.get_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Currency '{ref}' not found")
    return row
