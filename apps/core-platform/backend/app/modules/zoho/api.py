"""HTTP endpoints for Zoho sync state (api layer — thin, delegates to service).

`GET /items` and `GET /items/{id}` were REMOVED on 2026-09-18: they proxied
Zoho on every cache miss, which makes Zoho a synchronous dependency of a user
request (forbidden by the platform's prime directive) and spends the daily
call budget per field rep. Item reads come from the local mirror once the
items module lands; until then there is no item endpoint at all rather than a
budget-burning one.

See docs/zoho-sync-implementation/README.md (Phase 1) and
docs/zoho-sync-platform-architecture.md §2.2 finding N11.
"""

from fastapi import APIRouter

from app.common.exception.errors import NotFoundError
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.users.deps import CurrentUser
from app.modules.zoho import service
from app.modules.zoho.schema import SyncStateOut

router = APIRouter()


@router.get("/sync/{entity}", response_model=ResponseModel[SyncStateOut])
async def sync_status(_: CurrentUser, db: DBSession, entity: str):
    state = await service.get_sync_status(db, entity)
    if state is None:
        raise NotFoundError(f"No sync state for entity '{entity}'")
    return ResponseModel(data=state)
