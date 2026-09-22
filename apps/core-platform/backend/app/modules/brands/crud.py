"""Data access for ``core.brands`` (crud layer — no business logic).

Lists use ``load_only`` (Slim); the detail read uses ``selectinload`` for the
manufacturer links (Fat). Every relationship on the models is ``lazy="raise"``,
so nothing here can trigger a lazy load.
"""

from __future__ import annotations

import uuid as uuid_lib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.modules.brands.model import Brand, BrandManufacturer

_SLIM_COLUMNS = (
    Brand.id, Brand.uuid, Brand.name, Brand.slug, Brand.code, Brand.status, Brand.kind,
    Brand.country_code, Brand.parent_id, Brand.is_verified,
)


async def list_brands(
    db: AsyncSession, *, q: str | None = None, status: str | None = None, kind: str | None = None,
    parent_id: int | None = None, page: int = 1, page_size: int = 100,
) -> list[Brand]:
    stmt = (
        select(Brand)
        .options(load_only(*_SLIM_COLUMNS))
        .order_by(Brand.name, Brand.id)
    )
    if q:
        stmt = stmt.where(Brand.name_normalized.ilike(f"%{q.strip().lower()}%"))
    if status:
        stmt = stmt.where(Brand.status == status)
    if kind:
        stmt = stmt.where(Brand.kind == kind)
    if parent_id is not None:
        stmt = stmt.where(Brand.parent_id == parent_id)
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_brand(db: AsyncSession, ref: str) -> Brand | None:
    """Local id or public uuid."""
    conditions = []
    if str(ref).isdigit():
        conditions.append(Brand.id == int(ref))
    else:
        try:
            conditions.append(Brand.uuid == uuid_lib.UUID(str(ref)))
        except ValueError:
            return None
    stmt = (
        select(Brand)
        .where(or_(*conditions))
        .options(selectinload(Brand.manufacturer_links))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_by_id(db: AsyncSession, brand_id: int) -> Brand | None:
    """Light read (no eager loads) — used for parent/cycle walks."""
    return await db.get(Brand, brand_id)


async def find_by_slug(db: AsyncSession, organization_id: int, slug: str) -> Brand | None:
    return await db.scalar(
        select(Brand).where(Brand.organization_id == organization_id, Brand.slug == slug).limit(1)
    )


async def find_by_code(db: AsyncSession, organization_id: int, code: str) -> Brand | None:
    return await db.scalar(
        select(Brand).where(Brand.organization_id == organization_id, Brand.code == code).limit(1)
    )


async def find_by_name(db: AsyncSession, organization_id: int, normalized: str) -> Brand | None:
    return await db.scalar(
        select(Brand).where(Brand.organization_id == organization_id,
                            Brand.name_normalized == normalized).limit(1)
    )


async def create_brand(db: AsyncSession, values: dict) -> Brand:
    brand = Brand(**values)
    db.add(brand)
    await db.flush()
    return brand


async def get_link(db: AsyncSession, brand_id: int, link_uuid: uuid_lib.UUID) -> BrandManufacturer | None:
    return await db.scalar(
        select(BrandManufacturer)
        .where(BrandManufacturer.brand_id == brand_id, BrandManufacturer.uuid == link_uuid)
        .limit(1)
    )


async def list_links(db: AsyncSession, brand_id: int) -> list[BrandManufacturer]:
    stmt = (
        select(BrandManufacturer)
        .where(BrandManufacturer.brand_id == brand_id)
        .order_by(BrandManufacturer.is_default.desc().nulls_last(), BrandManufacturer.id)
    )
    return list((await db.scalars(stmt)).all())


async def current_link(
    db: AsyncSession, brand_id: int, manufacturer_id: int, kind: str | None,
) -> BrandManufacturer | None:
    return await db.scalar(
        select(BrandManufacturer).where(
            BrandManufacturer.brand_id == brand_id,
            BrandManufacturer.manufacturer_id == manufacturer_id,
            BrandManufacturer.kind.is_not_distinct_from(kind),
            BrandManufacturer.valid_to.is_(None),
        ).limit(1)
    )


async def create_link(db: AsyncSession, values: dict) -> BrandManufacturer:
    link = BrandManufacturer(**values)
    db.add(link)
    await db.flush()
    return link


async def clear_other_defaults(
    db: AsyncSession, brand_id: int, kind: str | None, *, keep_id: int | None = None,
) -> None:
    """At most one current default per (brand, kind) — clear the old one rather
    than letting the partial unique index reject the write."""
    stmt = select(BrandManufacturer).where(
        BrandManufacturer.brand_id == brand_id,
        BrandManufacturer.kind.is_not_distinct_from(kind),
        BrandManufacturer.is_default.is_(True),
        BrandManufacturer.valid_to.is_(None),
    )
    if keep_id is not None:
        stmt = stmt.where(BrandManufacturer.id != keep_id)
    for other in (await db.scalars(stmt)).all():
        other.is_default = False
