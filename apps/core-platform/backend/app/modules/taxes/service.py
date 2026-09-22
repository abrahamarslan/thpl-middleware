"""Taxes business logic — reads the canonical tables only (zero Zoho calls)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, NotFoundError
from app.modules.taxes import crud
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.reference import GstTreatmentType


async def list_components(
    db: AsyncSession, *, tax_type: str | None = None, specific_type: str | None = None,
    organization_id: int | None = None, page: int = 1, page_size: int = 100,
) -> list[TaxComponent]:
    return await crud.list_components(
        db, tax_type=tax_type, specific_type=specific_type, organization_id=organization_id,
        page=page, page_size=page_size,
    )


async def get_component(db: AsyncSession, ref: str) -> TaxComponent:
    row = await crud.get_component_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Tax '{ref}' not found")
    return row


async def list_exemptions(db: AsyncSession, *, page: int = 1, page_size: int = 100) -> list[TaxExemption]:
    return await crud.list_exemptions(db, page=page, page_size=page_size)


async def list_gst_treatments(db: AsyncSession, *, category: str | None = None) -> list[GstTreatmentType]:
    return await crud.list_gst_treatments(db, category=category)


async def list_default_preferences(
    db: AsyncSession, *, organization_id: int | None = None
) -> list[OrgDefaultTaxPreference]:
    return await crud.list_default_preferences(db, organization_id=organization_id)


async def sources_for(db: AsyncSession, component: TaxComponent) -> list[dict[str, Any]]:
    """Which external systems this component is linked to, and under what id."""
    from app.modules.sync.crosswalk import by_entity

    rows = (await db.execute(by_entity(
        tenant_id=component.tenant_id, entity_table=TaxComponent.__table__.fullname,
        entity_ids=[component.id],
    ))).all()
    return [
        {"source_system": source, "module": module, "external_id": external_id, "link_state": link_state}
        for source, module, external_id, _entity_id, link_state in rows
    ]


def to_zoho_payload(component: TaxComponent, *, create: bool = False) -> dict[str, Any]:
    """This leaf tax as the body ``/settings/taxes`` expects.

    Read-only attributes and everything not verified as writable are structurally
    excluded (``direction=IN``). Raises ``TranslationError`` when a required create
    argument is missing, so a payload Zoho would reject costs nothing instead of an
    API call. A group is a different resource with a different body — refused here.
    """
    from app.modules.sync.translation import WriteIntent
    from app.modules.taxes.zoho.translator import TAX_TRANSLATOR

    if component.is_group:
        raise AppError("A tax group is written through /settings/taxgroups, not /settings/taxes")
    return TAX_TRANSLATOR.encode(component, intent=WriteIntent.CREATE if create else WriteIntent.UPDATE)
