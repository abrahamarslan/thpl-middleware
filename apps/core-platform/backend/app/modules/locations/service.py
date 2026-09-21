"""Locations business logic — reads from the local mirror only (zero Zoho calls)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.locations import crud
from app.modules.locations.model import ZohoLocation


async def list_locations(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoLocation]:
    return await crud.list_all(db, status=status, page=page, page_size=page_size)


async def get_location(db: AsyncSession, ref: str) -> ZohoLocation:
    row = await crud.get_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Location '{ref}' not found")
    return row
