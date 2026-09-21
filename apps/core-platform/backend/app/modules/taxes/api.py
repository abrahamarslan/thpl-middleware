"""HTTP endpoints for taxes (mounted at /api/zoho/taxes, read-only).

`{ref}` accepts the local id or the Zoho id.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.taxes import service
from app.modules.taxes.schema import TaxOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[TaxOut]])
async def list_taxes(
    _: CurrentUser,
    db: DBSession,
    specific_type: str | None = Query(None, description="e.g. igst, cgst, sgst (India)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_taxes(db, specific_type=specific_type, page=page, page_size=page_size)
    return ResponseModel(data=[TaxOut.model_validate(r) for r in rows])


@router.get("/{ref}", response_model=ResponseModel[TaxOut])
async def get_tax(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=TaxOut.model_validate(await service.get_tax(db, ref)))
