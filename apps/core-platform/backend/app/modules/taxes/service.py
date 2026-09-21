"""Taxes business logic — reads from the local mirror only (zero Zoho calls)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.taxes import crud
from app.modules.taxes.model import ZohoTax


async def list_taxes(
    db: AsyncSession, *, specific_type: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoTax]:
    return await crud.list_all(db, specific_type=specific_type, page=page, page_size=page_size)


async def get_tax(db: AsyncSession, ref: str) -> ZohoTax:
    row = await crud.get_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Tax '{ref}' not found")
    return row
