"""Data access for ``core.manufacturers`` (crud layer — no business logic)."""

from __future__ import annotations

import uuid as uuid_lib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.modules.manufacturers.model import Manufacturer, ManufacturerIdentifier

_SLIM_COLUMNS = (
    Manufacturer.id, Manufacturer.uuid, Manufacturer.name, Manufacturer.slug, Manufacturer.legal_name,
    Manufacturer.code, Manufacturer.status, Manufacturer.country_code, Manufacturer.is_verified,
)


async def list_manufacturers(
    db: AsyncSession, *, q: str | None = None, status: str | None = None,
    page: int = 1, page_size: int = 100,
) -> list[Manufacturer]:
    stmt = (
        select(Manufacturer)
        .options(load_only(*_SLIM_COLUMNS))
        .order_by(Manufacturer.name, Manufacturer.id)
    )
    if q:
        stmt = stmt.where(Manufacturer.name_normalized.ilike(f"%{q.strip().lower()}%"))
    if status:
        stmt = stmt.where(Manufacturer.status == status)
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_manufacturer(db: AsyncSession, ref: str) -> Manufacturer | None:
    conditions = []
    if str(ref).isdigit():
        conditions.append(Manufacturer.id == int(ref))
    else:
        try:
            conditions.append(Manufacturer.uuid == uuid_lib.UUID(str(ref)))
        except ValueError:
            return None
    stmt = (
        select(Manufacturer)
        .where(or_(*conditions))
        .options(selectinload(Manufacturer.identifiers))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_by_id(db: AsyncSession, manufacturer_id: int) -> Manufacturer | None:
    return await db.get(Manufacturer, manufacturer_id)


async def find_by_slug(db: AsyncSession, organization_id: int, slug: str) -> Manufacturer | None:
    return await db.scalar(
        select(Manufacturer).where(Manufacturer.organization_id == organization_id,
                                   Manufacturer.slug == slug).limit(1)
    )


async def find_by_code(db: AsyncSession, organization_id: int, code: str) -> Manufacturer | None:
    return await db.scalar(
        select(Manufacturer).where(Manufacturer.organization_id == organization_id,
                                   Manufacturer.code == code).limit(1)
    )


async def find_by_name(db: AsyncSession, organization_id: int, normalized: str) -> Manufacturer | None:
    return await db.scalar(
        select(Manufacturer).where(Manufacturer.organization_id == organization_id,
                                   Manufacturer.name_normalized == normalized).limit(1)
    )


async def create_manufacturer(db: AsyncSession, values: dict) -> Manufacturer:
    manufacturer = Manufacturer(**values)
    db.add(manufacturer)
    await db.flush()
    return manufacturer


async def list_identifiers(db: AsyncSession, manufacturer_id: int) -> list[ManufacturerIdentifier]:
    stmt = (
        select(ManufacturerIdentifier)
        .where(ManufacturerIdentifier.manufacturer_id == manufacturer_id)
        .order_by(ManufacturerIdentifier.kind, ManufacturerIdentifier.id)
    )
    return list((await db.scalars(stmt)).all())


async def get_identifier(
    db: AsyncSession, manufacturer_id: int, identifier_uuid: uuid_lib.UUID,
) -> ManufacturerIdentifier | None:
    return await db.scalar(
        select(ManufacturerIdentifier)
        .where(ManufacturerIdentifier.manufacturer_id == manufacturer_id,
               ManufacturerIdentifier.uuid == identifier_uuid)
        .limit(1)
    )


async def current_identifier(
    db: AsyncSession, manufacturer_id: int, kind: str | None, value_normalized: str,
) -> ManufacturerIdentifier | None:
    return await db.scalar(
        select(ManufacturerIdentifier).where(
            ManufacturerIdentifier.manufacturer_id == manufacturer_id,
            ManufacturerIdentifier.kind.is_not_distinct_from(kind),
            ManufacturerIdentifier.value_normalized == value_normalized,
        ).limit(1)
    )


async def create_identifier(db: AsyncSession, values: dict) -> ManufacturerIdentifier:
    identifier = ManufacturerIdentifier(**values)
    db.add(identifier)
    await db.flush()
    return identifier
