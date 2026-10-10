"""Data access for the ``core`` registry tables (crud layer — no business logic)."""

from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entities.model import EntityAlias, EntityType


@dataclass(frozen=True, slots=True)
class OwnerInfo:
    """What the registry says about one polymorphic owner: does it exist, and where does it live?"""

    exists: bool
    tenant_id: int | None = None
    organization_id: int | None = None


async def owner_info(db: AsyncSession, entity_type_code: str, owner_id: int) -> OwnerInfo:
    """Does the owner exist, and which tenant/organization does it belong to?

    The table is known only from ``core.entity_types`` (``target_schema.target_table``), so
    the read is dynamic. Both identifiers come from that registry row, never from a request,
    and are quoted by PostgreSQL's ``format('%I')`` rather than concatenated. A class whose
    table has no ``tenant_id`` / ``organization_id`` reports ``None`` for it — the database
    trigger (``core.assert_owner_scope``) checks the same columns the same way. Shared by every
    polymorphic-assignment module (taxes, accounting).
    """
    registered = (await db.execute(
        select(EntityType.target_schema, EntityType.target_table).where(EntityType.code == entity_type_code)
    )).first()
    if registered is None:
        return OwnerInfo(exists=False)
    schema, table = registered
    qualified = str(await db.scalar(text("SELECT format('%I.%I', CAST(:s AS text), CAST(:t AS text))"),
                                    {"s": schema, "t": table}))
    scope_columns = set((await db.scalars(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_schema = :s AND table_name = :t AND column_name IN ('tenant_id', 'organization_id')"),
        {"s": schema, "t": table},
    )).all())
    tenant_sql = "tenant_id" if "tenant_id" in scope_columns else "NULL::bigint"
    org_sql = "organization_id" if "organization_id" in scope_columns else "NULL::bigint"
    if (schema, table) == ("org_management", "organizations"):
        org_sql = "id"            # an organization's "organization" is itself
    row = (await db.execute(
        text(f"SELECT {tenant_sql}, {org_sql} FROM {qualified} WHERE id = :id"), {"id": owner_id},
    )).first()
    if row is None:
        return OwnerInfo(exists=False)
    return OwnerInfo(exists=True, tenant_id=row[0], organization_id=row[1])


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
