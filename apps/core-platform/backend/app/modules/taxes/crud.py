"""Data access for the tax schema (crud layer — no business logic).

Loader strategy, stated once: every relationship on these models is
``lazy="raise"``. Lists use ``load_only`` (Slim); the single-component read uses
``selectinload(members)`` + ``joinedload(member_tax)`` (Fat). Nothing here can
trigger a lazy load.
"""

import uuid as uuid_lib

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only, selectinload

from app.modules.sync.models import SyncRecord
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.enums import TAX_SCHEMA
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.reference import GstTreatmentType

#: Crosswalk modules whose rows land in tax.tax_components.
_COMPONENT_MODULES = ("taxes", "tax_groups")

_SLIM_COLUMNS = (
    TaxComponent.id, TaxComponent.uuid, TaxComponent.tax_name, TaxComponent.tax_display_name,
    TaxComponent.tax_percentage, TaxComponent.tax_type, TaxComponent.tax_specific_type,
    TaxComponent.tax_specification, TaxComponent.is_default_tax, TaxComponent.is_inactive,
    TaxComponent.status,
)


async def list_components(
    db: AsyncSession, *, tax_type: str | None = None, specific_type: str | None = None,
    organization_id: int | None = None, page: int = 1, page_size: int = 100,
) -> list[TaxComponent]:
    stmt = select(TaxComponent).options(load_only(*_SLIM_COLUMNS)).order_by(TaxComponent.tax_name, TaxComponent.id)
    if tax_type:
        stmt = stmt.where(TaxComponent.tax_type == tax_type)
    if specific_type:
        stmt = stmt.where(TaxComponent.tax_specific_type == specific_type)
    if organization_id is not None:
        # An active grant, not merely a row: is_active is the per-organization switch.
        stmt = stmt.where(TaxComponent.id.in_(
            select(OrganizationTaxComponent.tax_component_id).where(
                OrganizationTaxComponent.organization_id == organization_id,
                OrganizationTaxComponent.is_active.is_(True),
            )
        ))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list((await db.scalars(stmt)).all())


async def get_component_by_ref(db: AsyncSession, ref: str) -> TaxComponent | None:
    """Local id, public uuid, or the source's own id (resolved through the crosswalk)."""
    conditions = [
        TaxComponent.id.in_(
            select(SyncRecord.entity_id).where(
                SyncRecord.source_system == "zoho",
                SyncRecord.module.in_(_COMPONENT_MODULES),
                SyncRecord.entity_table == f"{TAX_SCHEMA}.tax_components",
                SyncRecord.external_id == ref,
            )
        )
    ]
    if ref.isdigit():
        conditions.append(TaxComponent.id == int(ref))
    else:
        try:
            conditions.append(TaxComponent.uuid == uuid_lib.UUID(ref))
        except ValueError:
            pass
    stmt = (
        select(TaxComponent)
        .where(or_(*conditions))
        .options(selectinload(TaxComponent.members).joinedload(TaxGroupMember.member_tax))
        .limit(1)
    )
    return await db.scalar(stmt)


async def list_exemptions(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[TaxExemption]:
    stmt = select(TaxExemption).order_by(TaxExemption.tax_exemption_code, TaxExemption.id)
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def list_gst_treatments(db: AsyncSession, *, category: str | None = None) -> list[GstTreatmentType]:
    stmt = select(GstTreatmentType).order_by(GstTreatmentType.code)
    if category:
        stmt = stmt.where(GstTreatmentType.category == category)
    return list((await db.scalars(stmt)).all())


async def list_default_preferences(
    db: AsyncSession, *, organization_id: int | None = None
) -> list[OrgDefaultTaxPreference]:
    stmt = (
        select(OrgDefaultTaxPreference)
        .options(joinedload(OrgDefaultTaxPreference.default_tax).load_only(*_SLIM_COLUMNS))
        .order_by(OrgDefaultTaxPreference.organization_id, OrgDefaultTaxPreference.tax_specification)
    )
    if organization_id is not None:
        # An organization's own default wins; the tenant-wide default (NULL) is its fallback.
        stmt = stmt.where(or_(OrgDefaultTaxPreference.organization_id == organization_id,
                              OrgDefaultTaxPreference.organization_id.is_(None)))
    return list((await db.scalars(stmt)).unique().all())
