"""Data access for the catalogue masters (crud layer — SQL only, no business rules).

Every read goes through the session's tenancy filter (tenant) and the global soft-delete filter; lists
add the organization explicitly. Lists use ``load_only`` (Slim); nothing here touches a relationship,
so nothing can lazy-load.
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.catalogue.model import (
    Attribute,
    AttributeOption,
    ItemGroup,
    PackagingType,
    SalesChannel,
    Unit,
    UqcCode,
)

M = TypeVar("M")

#: Slim column sets — what the list endpoints render, nothing more.
SLIM: dict[type, tuple] = {
    Unit: (Unit.id, Unit.uuid, Unit.code, Unit.name, Unit.unit_class, Unit.uqc_code, Unit.decimal_places,
           Unit.si_factor, Unit.is_system, Unit.status),
    PackagingType: (PackagingType.id, PackagingType.uuid, PackagingType.code, PackagingType.name,
                    PackagingType.is_container, PackagingType.is_display_unit, PackagingType.is_stackable,
                    PackagingType.icon, PackagingType.status),
    SalesChannel: (SalesChannel.id, SalesChannel.uuid, SalesChannel.code, SalesChannel.name,
                   SalesChannel.channel_kind, SalesChannel.zoho_code, SalesChannel.position, SalesChannel.status),
    ItemGroup: (ItemGroup.id, ItemGroup.uuid, ItemGroup.code, ItemGroup.name, ItemGroup.parent_id,
                ItemGroup.is_visible, ItemGroup.show_in_menu, ItemGroup.display_order, ItemGroup.status),
    Attribute: (Attribute.id, Attribute.uuid, Attribute.code, Attribute.name, Attribute.input_type,
                Attribute.unit_id, Attribute.status),
}

#: Default ordering per model (deterministic pages).
ORDER: dict[type, tuple] = {
    Unit: (Unit.unit_class, Unit.code, Unit.id),
    PackagingType: (PackagingType.code, PackagingType.id),
    SalesChannel: (SalesChannel.position, SalesChannel.code, SalesChannel.id),
    ItemGroup: (ItemGroup.display_order, ItemGroup.name, ItemGroup.id),
    Attribute: (Attribute.name, Attribute.id),
}


def _ref_condition(model: type, ref: str):
    """``ref`` is the public uuid (preferred) or the numeric id."""
    if str(ref).isdigit():
        return model.id == int(ref)
    try:
        return model.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        return None


async def get_by_ref(db: AsyncSession, model: type[M], ref: str, *, organization_id: int) -> M | None:
    condition = _ref_condition(model, ref)
    if condition is None:
        return None
    return await db.scalar(
        select(model).where(condition, model.organization_id == organization_id).limit(1)
    )


async def get_by_id(db: AsyncSession, model: type[M], row_id: int, *, organization_id: int) -> M | None:
    return await db.scalar(
        select(model).where(model.id == row_id, model.organization_id == organization_id).limit(1)
    )


async def find_by(db: AsyncSession, model: type[M], *, organization_id: int, **eq: Any) -> M | None:
    stmt = select(model).where(model.organization_id == organization_id)
    for column, value in eq.items():
        stmt = stmt.where(getattr(model, column) == value)
    return await db.scalar(stmt.limit(1))


async def list_page(
    db: AsyncSession, model: type[M], *, organization_id: int, q: str | None = None,
    filters: dict[str, Any] | None = None, limit: int = 100, offset: int = 0,
) -> tuple[list[M], int]:
    """A slim page plus the total. ``q`` matches code or name (case-insensitive substring)."""
    stmt = select(model).where(model.organization_id == organization_id)
    for column, value in (filters or {}).items():
        if value is not None:
            stmt = stmt.where(getattr(model, column) == value)
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(model.code.ilike(pattern), model.name.ilike(pattern)))
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.scalars(
        stmt.options(load_only(*SLIM[model])).order_by(*ORDER[model]).offset(offset).limit(limit)
    )
    return list(rows.all()), int(total or 0)


async def list_all(db: AsyncSession, model: type[M], *, organization_id: int) -> list[M]:
    """Every live row of the organization (bounded masters: item-group trees)."""
    rows = await db.scalars(
        select(model).where(model.organization_id == organization_id)
        .options(load_only(*SLIM[model])).order_by(*ORDER[model])
    )
    return list(rows.all())


async def list_uqc_codes(db: AsyncSession, *, active_only: bool = True) -> list[UqcCode]:
    stmt = select(UqcCode).order_by(UqcCode.code)
    if active_only:
        stmt = stmt.where(UqcCode.is_active.is_(True))
    return list((await db.scalars(stmt)).all())


async def get_uqc(db: AsyncSession, code: str) -> UqcCode | None:
    return await db.get(UqcCode, code)


async def list_options(db: AsyncSession, attribute_id: int) -> list[AttributeOption]:
    rows = await db.scalars(
        select(AttributeOption).where(AttributeOption.attribute_id == attribute_id)
        .order_by(AttributeOption.position, AttributeOption.value_normalized, AttributeOption.id)
    )
    return list(rows.all())


async def find_option(db: AsyncSession, attribute_id: int, normalized: str) -> AttributeOption | None:
    return await db.scalar(
        select(AttributeOption).where(AttributeOption.attribute_id == attribute_id,
                                      AttributeOption.value_normalized == normalized).limit(1)
    )


async def get_option(db: AsyncSession, attribute_id: int, ref: str) -> AttributeOption | None:
    condition = _ref_condition(AttributeOption, ref)
    if condition is None:
        return None
    return await db.scalar(
        select(AttributeOption).where(condition, AttributeOption.attribute_id == attribute_id).limit(1)
    )


async def unit_in_use(db: AsyncSession, unit_id: int) -> bool:
    """Is the unit referenced by a live catalogue row? (phase 2 adds items / item_units)."""
    checks = (
        select(PackagingType.id).where(or_(PackagingType.weight_unit_id == unit_id,
                                           PackagingType.dimension_unit_id == unit_id)),
        select(Attribute.id).where(Attribute.unit_id == unit_id),
    )
    for stmt in checks:
        if await db.scalar(stmt.limit(1)) is not None:
            return True
    return False


async def group_children_exist(db: AsyncSession, group_id: int) -> bool:
    return await db.scalar(select(ItemGroup.id).where(ItemGroup.parent_id == group_id).limit(1)) is not None


__all__ = [
    "SLIM", "find_by", "find_option", "get_by_id", "get_by_ref", "get_option", "get_uqc",
    "group_children_exist", "list_all", "list_options", "list_page", "list_uqc_codes", "unit_in_use",
]
