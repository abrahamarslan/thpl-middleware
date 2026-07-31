"""HTTP endpoints for Zoho data (api layer — thin, delegates to service)."""

from fastapi import APIRouter, Query

from app.common.exception.errors import NotFoundError
from app.common.response.schema import ResponseModel
from app.modules.users.deps import CurrentUser
from app.database.db import DBSession
from app.modules.zoho import service
from app.modules.zoho.schema import SyncStateOut, ZohoItem

router = APIRouter()


@router.get("/items", response_model=ResponseModel[list[ZohoItem]])
async def list_items(_: CurrentUser, page: int = Query(1, ge=1)):
    """Prices & stock for the sales app — served from short-TTL cache."""
    return ResponseModel(data=await service.list_items(page=page))


@router.get("/items/{item_id}", response_model=ResponseModel[ZohoItem])
async def get_item(_: CurrentUser, item_id: str):
    return ResponseModel(data=await service.get_item(item_id))


@router.get("/sync/{entity}", response_model=ResponseModel[SyncStateOut])
async def sync_status(_: CurrentUser, db: DBSession, entity: str):
    state = await service.get_sync_status(db, entity)
    if state is None:
        raise NotFoundError(f"No sync state for entity '{entity}'")
    return ResponseModel(data=state)
