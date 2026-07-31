"""HTTP endpoints for organizations (mounted at /api/zoho/organizations).

Local apps talk ONLY to these endpoints; the sync engine reconciles with
Zoho in the background. `{ref}` accepts the local id or the Zoho id.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.users.deps import CurrentUser
from app.modules.zoho.organizations import service
from app.modules.zoho.organizations.schema import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.modules.zoho.sync.config import SyncStrategyName
from app.modules.zoho.sync.schemas import SyncRunAccepted

router = APIRouter()


@router.get("", response_model=ResponseModel[list[OrganizationOut]])
async def list_organizations(
    _: CurrentUser,
    db: DBSession,
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_organizations(db, active_only=active_only, page=page, page_size=page_size)
    return ResponseModel(data=[OrganizationOut.model_validate(r) for r in rows])


@router.post("", response_model=ResponseModel[OrganizationOut], status_code=201)
async def create_organization(user: CurrentUser, db: DBSession, payload: OrganizationCreate):
    """Outbox create: row is written locally NOW (zoho_id NULL) and pushed to
    Zoho asynchronously; poll sync_status/zoho_id for convergence."""
    row = await service.create_organization(db, payload, actor_id=user.id)
    return ResponseModel(data=OrganizationOut.model_validate(row), msg="Created locally; push to Zoho queued")


@router.post("/sync", response_model=ResponseModel[SyncRunAccepted], status_code=202)
async def sync_organizations(
    _: CurrentUser,
    mode: SyncStrategyName | None = Query(None, description="Override configured strategy"),
):
    task_id = service.trigger_sync(mode.value if mode else None)
    return ResponseModel(
        data=SyncRunAccepted(module="organizations", mode=(mode or SyncStrategyName.FULL).value, task_id=task_id),
        msg="Sync queued",
    )


@router.get("/{ref}", response_model=ResponseModel[OrganizationOut])
async def get_organization(_: CurrentUser, db: DBSession, ref: str):
    row = await service.get_organization(db, ref)
    return ResponseModel(data=OrganizationOut.model_validate(row))


@router.put("/{ref}", response_model=ResponseModel[OrganizationOut])
async def update_organization(user: CurrentUser, db: DBSession, ref: str, payload: OrganizationUpdate):
    row = await service.update_organization(db, ref, payload, actor_id=user.id)
    return ResponseModel(data=OrganizationOut.model_validate(row), msg="Updated locally; push to Zoho queued")


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_organization(user: CurrentUser, db: DBSession, ref: str):
    await service.delete_organization(db, ref, actor_id=user.id)
    return ResponseModel(data=None, msg="Soft-deleted locally; delete push to Zoho queued")
