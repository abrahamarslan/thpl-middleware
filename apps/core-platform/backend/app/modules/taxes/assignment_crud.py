"""Data access for tax assignments (crud layer — no business logic).

Loader strategy, stated once: every relationship is ``lazy="raise"``. Reads bring
the tax with ``joinedload(tax_component)`` (many-to-one, one row each) using the
Slim column set; an exemption is fetched the same way. Nothing here can trigger a
lazy load.
"""

from __future__ import annotations

import uuid as uuid_lib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.entities.model import EntityType
from app.modules.taxes.assignment import TaxableEntityType, TaxAssignment
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference

_COMPONENT_SLIM = (
    TaxComponent.id, TaxComponent.uuid, TaxComponent.tax_name, TaxComponent.tax_display_name,
    TaxComponent.tax_percentage, TaxComponent.tax_type, TaxComponent.tax_specific_type,
    TaxComponent.tax_specification, TaxComponent.is_default_tax, TaxComponent.is_inactive,
    TaxComponent.status,
)


@dataclass(frozen=True, slots=True)
class OwnerInfo:
    """What the registry says about one owning entity."""

    exists: bool
    tenant_id: int | None = None
    organization_id: int | None = None


# ── policy ───────────────────────────────────────────────────────────────────

async def get_policy(db: AsyncSession, entity_type_code: str) -> TaxableEntityType | None:
    return await db.scalar(
        select(TaxableEntityType).where(TaxableEntityType.entity_type_code == entity_type_code).limit(1)
    )


async def list_policies(db: AsyncSession) -> list[TaxableEntityType]:
    return list((await db.scalars(select(TaxableEntityType).order_by(TaxableEntityType.entity_type_code))).all())


# ── the owner (resolved through the registry) ────────────────────────────────

async def owner_info(db: AsyncSession, entity_type_code: str, owner_id: int) -> OwnerInfo:
    """Does the owner exist, and which tenant/organization does it belong to?

    The table is known only from ``core.entity_types`` (``target_schema.target_table``),
    so the read is dynamic. Both identifiers come from that registry row, never from a
    request, and are quoted by PostgreSQL's ``format('%I')`` rather than concatenated.
    A class whose table has no ``tenant_id`` / ``organization_id`` reports ``None`` for it
    — the database trigger checks the same columns the same way.
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
    row = (await db.execute(
        text(f"SELECT {tenant_sql}, {org_sql} FROM {qualified} WHERE id = :id"), {"id": owner_id},
    )).first()
    if row is None:
        return OwnerInfo(exists=False)
    return OwnerInfo(exists=True, tenant_id=row[0], organization_id=row[1])


# ── assignments ──────────────────────────────────────────────────────────────

def _with_targets():
    return (
        joinedload(TaxAssignment.tax_component).load_only(*_COMPONENT_SLIM),
        joinedload(TaxAssignment.tax_exemption),
    )


async def list_for_owner(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, include_pending: bool = True,
) -> list[TaxAssignment]:
    stmt = (
        select(TaxAssignment)
        .where(TaxAssignment.owner_type_code == owner_type_code, TaxAssignment.owner_id == owner_id)
        .options(*_with_targets())
        .order_by(TaxAssignment.position, TaxAssignment.id)
    )
    if not include_pending:
        stmt = stmt.where(or_(TaxAssignment.tax_component_id.is_not(None),
                              TaxAssignment.tax_exemption_id.is_not(None)))
    return list((await db.scalars(stmt)).unique().all())


async def get_assignment_by_ref(db: AsyncSession, ref: str) -> TaxAssignment | None:
    condition = None
    if ref.isdigit():
        condition = TaxAssignment.id == int(ref)
    else:
        try:
            condition = TaxAssignment.uuid == uuid_lib.UUID(ref)
        except ValueError:
            return None
    return await db.scalar(select(TaxAssignment).where(condition).options(*_with_targets()).limit(1))


async def usage_of_component(db: AsyncSession, tax_component_id: int) -> int:
    """How many live assignments carry this tax — the blast radius of changing it."""
    return int(await db.scalar(
        select(func.count()).select_from(TaxAssignment).where(TaxAssignment.tax_component_id == tax_component_id)
    ) or 0)


# ── the taxes an assignment may name ─────────────────────────────────────────

async def components_by_id(db: AsyncSession, ids: Iterable[int]) -> dict[int, TaxComponent]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.scalars(
        select(TaxComponent).where(TaxComponent.id.in_(wanted))
        .options(selectinload(TaxComponent.members).joinedload(TaxGroupMember.member_tax))
    )
    return {row.id: row for row in rows.all()}


async def exemptions_by_id(db: AsyncSession, ids: Iterable[int]) -> dict[int, TaxExemption]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.scalars(select(TaxExemption).where(TaxExemption.id.in_(wanted)))
    return {row.id: row for row in rows.all()}


async def get_exemption_by_ref(db: AsyncSession, ref: str) -> TaxExemption | None:
    """Local id or public uuid (an exemption's source id is not a stable key: see exemption.py)."""
    if ref.isdigit():
        condition = TaxExemption.id == int(ref)
    else:
        try:
            condition = TaxExemption.uuid == uuid_lib.UUID(ref)
        except ValueError:
            return None
    return await db.scalar(select(TaxExemption).where(condition).limit(1))


async def granted_component_ids(
    db: AsyncSession, organization_id: int, ids: Sequence[int],
) -> set[int]:
    """Which of ``ids`` this organization may use (an ACTIVE grant, not merely a row)."""
    if not ids:
        return set()
    rows = await db.scalars(select(OrganizationTaxComponent.tax_component_id).where(
        OrganizationTaxComponent.organization_id == organization_id,
        OrganizationTaxComponent.tax_component_id.in_(set(ids)),
        OrganizationTaxComponent.is_active.is_(True),
    ))
    return set(rows.all())


async def default_component_for(
    db: AsyncSession, organization_id: int | None, specification: str,
) -> TaxComponent | None:
    """The organization's default tax for a context; its own wins over the tenant-wide one."""
    scope = OrgDefaultTaxPreference.organization_id.is_(None)
    if organization_id is not None:
        scope = or_(OrgDefaultTaxPreference.organization_id == organization_id, scope)
    stmt = (
        select(OrgDefaultTaxPreference)
        .where(OrgDefaultTaxPreference.tax_specification == specification, scope)
        .options(joinedload(OrgDefaultTaxPreference.default_tax))
        .order_by(OrgDefaultTaxPreference.organization_id.asc().nulls_last())
        .limit(1)
    )
    preference = await db.scalar(stmt)
    return None if preference is None else preference.default_tax


__all__ = [
    "OwnerInfo",
    "components_by_id",
    "default_component_for",
    "exemptions_by_id",
    "get_assignment_by_ref",
    "get_exemption_by_ref",
    "get_policy",
    "granted_component_ids",
    "list_for_owner",
    "list_policies",
    "owner_info",
    "usage_of_component",
]
