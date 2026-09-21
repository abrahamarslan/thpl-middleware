"""HTTP endpoints for locations (mounted at /api/zoho/locations, read-only).

`{ref}` accepts the local id or the Zoho id.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.locations import service
from app.modules.locations.schema import LocationOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[list[LocationOut]])
async def list_locations(
    _: CurrentUser,
    db: DBSession,
    status: str | None = Query(None, pattern="^(active|inactive)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    rows = await service.list_locations(db, status=status, page=page, page_size=page_size)
    return ResponseModel(data=[LocationOut.model_validate(r) for r in rows])


@router.get("/{ref}", response_model=ResponseModel[LocationOut])
async def get_location(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel(data=LocationOut.model_validate(await service.get_location(db, ref)))
