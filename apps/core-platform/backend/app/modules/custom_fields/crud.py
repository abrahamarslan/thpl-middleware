"""Data access for the custom-fields engine (crud layer — no business logic).

Every definition/value read is filtered by the caller's ``organization_id``
explicitly: the global soft-delete listener filters ``tenant_id`` only, and
these tables are organization-scoped. Lists use ``load_only`` (Slim); the detail
read eager-loads the definition's data type. All model relationships are
``lazy="raise"``, so nothing here can trigger a lazy load.
"""

from __future__ import annotations

import uuid as uuid_lib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue

_DEFINITION_SLIM = (
    FieldDefinition.id, FieldDefinition.uuid, FieldDefinition.owner_type_code,
    FieldDefinition.data_type_id, FieldDefinition.api_name, FieldDefinition.label,
    FieldDefinition.is_active, FieldDefinition.is_mandatory, FieldDefinition.sort_order,
    FieldDefinition.pii_type,
)


# ── data types (global lookup) ───────────────────────────────────────────────

async def list_data_types(db: AsyncSession) -> list[DataType]:
    stmt = select(DataType).order_by(DataType.code)
    return list((await db.scalars(stmt)).all())


async def get_data_type_by_id(db: AsyncSession, data_type_id: int) -> DataType | None:
    return await db.get(DataType, data_type_id)


async def get_data_type_by_code(db: AsyncSession, code: str) -> DataType | None:
    return await db.scalar(select(DataType).where(DataType.code == code).limit(1))


# ── field definitions ────────────────────────────────────────────────────────

async def list_definitions(
    db: AsyncSession, organization_id: int, *, owner_type_code: str | None = None,
    is_active: bool | None = None, page: int = 1, page_size: int = 100,
) -> list[FieldDefinition]:
    stmt = (
        select(FieldDefinition)
        .where(FieldDefinition.organization_id == organization_id)
        .options(load_only(*_DEFINITION_SLIM))
        .order_by(FieldDefinition.sort_order.nulls_last(), FieldDefinition.api_name)
    )
    if owner_type_code:
        stmt = stmt.where(FieldDefinition.owner_type_code == owner_type_code)
    if is_active is not None:
        stmt = stmt.where(FieldDefinition.is_active.is_(is_active))
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def get_definition(db: AsyncSession, ref: str, organization_id: int) -> FieldDefinition | None:
    """Local id or public uuid, within the caller's organization."""
    conditions = []
    if str(ref).isdigit():
        conditions.append(FieldDefinition.id == int(ref))
    else:
        try:
            conditions.append(FieldDefinition.uuid == uuid_lib.UUID(str(ref)))
        except ValueError:
            return None
    stmt = (
        select(FieldDefinition)
        .where(or_(*conditions), FieldDefinition.organization_id == organization_id)
        .options(selectinload(FieldDefinition.data_type))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_definition_by_id(
    db: AsyncSession, field_definition_id: int, organization_id: int,
) -> FieldDefinition | None:
    """Light read (no eager loads) — used to validate a value write."""
    return await db.scalar(
        select(FieldDefinition)
        .where(FieldDefinition.id == field_definition_id,
               FieldDefinition.organization_id == organization_id)
        .limit(1)
    )


async def find_definition_by_api_name(
    db: AsyncSession, organization_id: int, owner_type_code: str, api_name: str,
) -> FieldDefinition | None:
    return await db.scalar(
        select(FieldDefinition).where(
            FieldDefinition.organization_id == organization_id,
            FieldDefinition.owner_type_code == owner_type_code,
            FieldDefinition.api_name == api_name,
        ).limit(1)
    )


async def create_definition(db: AsyncSession, values: dict) -> FieldDefinition:
    definition = FieldDefinition(**values)
    db.add(definition)
    await db.flush()
    return definition


# ── field values ─────────────────────────────────────────────────────────────

async def list_values_for_owner(
    db: AsyncSession, organization_id: int, owner_type_code: str, owner_id: int,
) -> list[FieldValue]:
    stmt = (
        select(FieldValue)
        .where(
            FieldValue.organization_id == organization_id,
            FieldValue.owner_type_code == owner_type_code,
            FieldValue.owner_id == owner_id,
        )
        .options(selectinload(FieldValue.field_definition))
        .order_by(FieldValue.field_definition_id)
    )
    return list((await db.scalars(stmt)).all())


async def get_value(db: AsyncSession, ref: str, organization_id: int) -> FieldValue | None:
    try:
        value_uuid = uuid_lib.UUID(str(ref))
    except ValueError:
        return None
    stmt = (
        select(FieldValue)
        .where(FieldValue.uuid == value_uuid, FieldValue.organization_id == organization_id)
        .options(selectinload(FieldValue.field_definition))
        .limit(1)
    )
    return await db.scalar(stmt)


async def get_value_by_id(
    db: AsyncSession, value_id: int, organization_id: int,
) -> FieldValue | None:
    return await db.scalar(
        select(FieldValue).where(FieldValue.id == value_id,
                                 FieldValue.organization_id == organization_id).limit(1)
    )


async def find_value(
    db: AsyncSession, organization_id: int, field_definition_id: int, owner_id: int,
) -> FieldValue | None:
    return await db.scalar(
        select(FieldValue).where(
            FieldValue.organization_id == organization_id,
            FieldValue.field_definition_id == field_definition_id,
            FieldValue.owner_id == owner_id,
        ).limit(1)
    )


async def list_live_values_for_definition(
    db: AsyncSession, organization_id: int, field_definition_id: int,
) -> list[FieldValue]:
    stmt = select(FieldValue).where(
        FieldValue.organization_id == organization_id,
        FieldValue.field_definition_id == field_definition_id,
    )
    return list((await db.scalars(stmt)).all())


async def create_value(db: AsyncSession, values: dict) -> FieldValue:
    value = FieldValue(**values)
    db.add(value)
    await db.flush()
    return value