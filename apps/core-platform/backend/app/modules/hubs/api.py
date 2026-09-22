"""Hub API — mounted at /api/hubs (the caller's tenant + organization)."""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.hubs import service
from app.modules.hubs.schema import HubCreate, HubOut, HubSlim, HubUpdate
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "hubs"


@router.get("", response_model=ResponseModel[list[HubSlim]])
async def list_hubs(
    _: CurrentUser,
    db: DBSession,
    hub_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_hubs(db, hub_type=hub_type, status=status, q=q, page=page, page_size=page_size)
    return ResponseModel.ok(data=[HubSlim.model_validate(r) for r in rows], module=_M, msg_key="listed")


@router.get("/{ref}", response_model=ResponseModel[HubOut])
async def get_hub(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=HubOut.model_validate(await service.get_hub(db, ref)), module=_M, msg_key="fetched")


@router.post("", response_model=ResponseModel[HubOut], status_code=201)
async def create_hub(user: CurrentUser, db: DBSession, body: HubCreate):
    hub = await service.create_hub(db, body, actor_id=user.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="created", code=hub.code)


@router.patch("/{ref}", response_model=ResponseModel[HubOut])
async def update_hub(user: CurrentUser, db: DBSession, ref: str, body: HubUpdate):
    hub = await service.update_hub(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="updated", code=hub.code)


@router.post("/{ref}/archive", response_model=ResponseModel[HubOut])
async def archive_hub(admin: TenantAdmin, db: DBSession, ref: str,
                      reason: str = Query(..., min_length=3, max_length=500)):
    hub = await service.archive_hub(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="archived", code=hub.code)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_hub(admin: TenantAdmin, db: DBSession, ref: str,
                     reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_hub(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
