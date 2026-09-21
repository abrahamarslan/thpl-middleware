"""HTTP endpoints for Zoho users (mounted at /api/zoho/users, read-only).

`{ref}` accepts the local id, the Zoho id or the email address.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.users.deps import CurrentUser
from app.modules.zoho_users import service
from app.modules.zoho_users.schema import ZohoUserOut

router = APIRouter()


@router.get("", response_model=ResponseModel[list[ZohoUserOut]])
async def list_zoho_users(
    _: CurrentUser,
    db: DBSession,
    status: str | None = Query(None, pattern="^(active|inactive|invited|deleted)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_users(db, status=status, page=page, page_size=page_size)
    return ResponseModel(data=[ZohoUserOut.model_validate(r) for r in rows])


@router.get("/{ref}", response_model=ResponseModel[ZohoUserOut])
async def get_zoho_user(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=ZohoUserOut.model_validate(await service.get_user(db, ref)))
