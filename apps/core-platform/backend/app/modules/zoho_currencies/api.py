"""HTTP endpoints for currencies (mounted at /api/zoho/currencies, read-only).

`{ref}` accepts the local id, the Zoho id or the ISO code.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.zoho_currencies import service
from app.modules.zoho_currencies.schema import CurrencyOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[CurrencyOut]])
async def list_currencies(
    _: CurrentUser,
    db: DBSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_currencies(db, page=page, page_size=page_size)
    return ResponseModel(data=[CurrencyOut.model_validate(r) for r in rows])


@router.get("/{ref}", response_model=ResponseModel[CurrencyOut])
async def get_currency(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=CurrencyOut.model_validate(await service.get_currency(db, ref)))
