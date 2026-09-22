"""Data access for the ``core`` registry tables (crud layer — no business logic)."""

from __future__ import annotations

import uuid as uuid_lib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entities.model import EntityAlias, EntityType


async def list_entity_types(db: AsyncSession) -> list[EntityType]:
    stmt = select(EntityType).order_by(EntityType.code)
    return list((await db.scalars(stmt)).all())


async def get_entity_type(db: AsyncSession, code: str) -> EntityType | None:
    return await db.scalar(select(EntityType).where(EntityType.code == code).limit(1))


async def list_aliases(
    db: AsyncSession, *, entity_type: str | None = None, entity_id: int | None = None,
    page: int = 1, page_size: int = 100,
) -> list[EntityAlias]:
    stmt = select(EntityAlias).order_by(EntityAlias.entity_type, EntityAlias.entity_id, EntityAlias.id)
    if entity_type:
        stmt = stmt.where(EntityAlias.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(EntityAlias.entity_id == entity_id)
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_alias(db: AsyncSession, alias_uuid: uuid_lib.UUID) -> EntityAlias | None:
    return await db.scalar(select(EntityAlias).where(EntityAlias.uuid == alias_uuid).limit(1))


async def create_alias(db: AsyncSession, values: dict) -> EntityAlias:
    alias = EntityAlias(**values)
    db.add(alias)
    await db.flush()
    return alias
