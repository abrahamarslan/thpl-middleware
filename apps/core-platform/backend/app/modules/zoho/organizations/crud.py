"""Data access for zoho_organizations (crud layer — no business logic)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho.organizations.model import ZohoOrganization


async def get(db: AsyncSession, local_id: int, *, include_deleted: bool = False) -> ZohoOrganization | None:
    return await db.get(
        ZohoOrganization, local_id, execution_options={"include_deleted": include_deleted}
    )


async def get_by_ref(db: AsyncSession, ref: str | int) -> ZohoOrganization | None:
    """Resolve by local PK or by zoho_id — API paths accept either."""
    conditions = [ZohoOrganization.zoho_id == str(ref)]
    if str(ref).isdigit():
        conditions.append(ZohoOrganization.id == int(ref))
    return await db.scalar(select(ZohoOrganization).where(or_(*conditions)).limit(1))


async def get_by_zoho_id(db: AsyncSession, zoho_id: str, *, include_deleted: bool = False) -> ZohoOrganization | None:
    stmt = (
        select(ZohoOrganization)
        .where(ZohoOrganization.zoho_id == zoho_id)
        .execution_options(include_deleted=include_deleted)
        .limit(1)
    )
    return await db.scalar(stmt)


async def list_all(
    db: AsyncSession, *, active_only: bool = False, page: int = 1, page_size: int = 50
) -> list[ZohoOrganization]:
    stmt = select(ZohoOrganization).order_by(ZohoOrganization.name.asc().nulls_last())
    if active_only:
        stmt = stmt.where(ZohoOrganization.is_org_active.is_(True))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def create(db: AsyncSession, values: dict) -> ZohoOrganization:
    row = ZohoOrganization(**values)
    db.add(row)
    await db.flush()
    return row
