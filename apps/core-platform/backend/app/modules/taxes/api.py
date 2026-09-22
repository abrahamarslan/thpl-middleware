"""HTTP endpoints for the tax module (mounted at /api/taxes, read-only).

Static paths are declared before ``/{ref}`` so ``exemptions`` is never read as a
reference. ``{ref}`` accepts the local id, the public uuid or the Zoho id.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.taxes import service
from app.modules.taxes.enums import GstTreatmentCategory, TaxType
from app.modules.taxes.schema import (
    GstTreatmentTypeOut,
    OrgDefaultTaxPreferenceOut,
    TaxComponentOut,
    TaxComponentSlimOut,
    TaxExemptionOut,
    TaxSourceOut,
)
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[TaxComponentSlimOut]])
async def list_taxes(
    _: CurrentUser,
    db: DBSession,
    tax_type: TaxType | None = Query(None, description="tax, compound_tax or tax_group"),
    specific_type: str | None = Query(None, description="e.g. igst, cgst, sgst (India)"),
    organization_id: int | None = Query(None, description="Only components actively granted to this organization"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_components(
        db, tax_type=tax_type.value if tax_type else None, specific_type=specific_type,
        organization_id=organization_id, page=page, page_size=page_size,
    )
    return ResponseModel(data=[TaxComponentSlimOut.model_validate(r) for r in rows])


@router.get("/exemptions", response_model=ResponseModel[list[TaxExemptionOut]])
async def list_exemptions(
    _: CurrentUser, db: DBSession,
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_exemptions(db, page=page, page_size=page_size)
    return ResponseModel(data=[TaxExemptionOut.model_validate(r) for r in rows])


@router.get("/gst-treatments", response_model=ResponseModel[list[GstTreatmentTypeOut]])
async def list_gst_treatments(
    _: CurrentUser, db: DBSession, category: GstTreatmentCategory | None = Query(None),
):
    rows = await service.list_gst_treatments(db, category=category.value if category else None)
    return ResponseModel(data=[GstTreatmentTypeOut.model_validate(r) for r in rows])


@router.get("/default-preferences", response_model=ResponseModel[list[OrgDefaultTaxPreferenceOut]])
async def list_default_preferences(
    _: CurrentUser, db: DBSession, organization_id: int | None = Query(None),
):
    rows = await service.list_default_preferences(db, organization_id=organization_id)
    return ResponseModel(data=[OrgDefaultTaxPreferenceOut.model_validate(r) for r in rows])


@router.get("/{ref}", response_model=ResponseModel[TaxComponentOut])
async def get_tax(_: CurrentUser, db: DBSession, ref: str):
    row = await service.get_component(db, ref)
    out = TaxComponentOut.model_validate(row)
    out.sources = [TaxSourceOut(**source) for source in await service.sources_for(db, row)]
    return ResponseModel(data=out)
