"""Zoho users business logic — reads from the local mirror only (zero Zoho calls)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.zoho_users import crud
from app.modules.zoho_users.model import ZohoUser


async def list_users(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 100
) -> list[ZohoUser]:
    return await crud.list_all(db, status=status, page=page, page_size=page_size)


async def get_user(db: AsyncSession, ref: str) -> ZohoUser:
    row = await crud.get_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Zoho user '{ref}' not found")
    return row
