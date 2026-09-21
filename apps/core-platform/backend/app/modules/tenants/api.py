"""Tenants API — mounted at /api/tenants.

| Route | Who | What |
|---|---|---|
| ``GET /current`` | any signed-in user | the caller's tenant |
| ``GET ""`` · ``GET /{ref}`` | platform admin | list / one tenant (ref = id, uuid or code) |
| ``POST ""`` | platform admin | create (optionally with its root organization) |
| ``PATCH /{ref}`` | platform admin | update (optimistic lock: ``row_version``) |
| ``POST /{ref}/status`` | platform admin | trial → active → suspended / cancelled (with reason) |

A suspended or cancelled tenant's users are refused at authentication.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.tenants import service
from app.modules.tenants.deps import PlatformAdmin
from app.modules.tenants.schema import TenantCreate, TenantOut, TenantStatusChange, TenantUpdate
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "tenants"


@router.get("/current", response_model=ResponseModel[TenantOut])
async def current_tenant(user: CurrentUser, db: DBSession):
    return ResponseModel.ok(data=TenantOut.model_validate(await service.get_tenant(db, user.tenant_id)))


@router.get("", response_model=ResponseModel[list[TenantOut]])
async def list_tenants(_: PlatformAdmin, db: DBSession, status: str | None = Query(None)):
    return ResponseModel.ok(data=[TenantOut.model_validate(t) for t in await service.list_tenants(db, status=status)])


@router.post("", response_model=ResponseModel[TenantOut], status_code=201)
async def create_tenant(admin: PlatformAdmin, db: DBSession, body: TenantCreate):
    tenant = await service.create_tenant(db, body, actor_id=admin.id)
    return ResponseModel.ok(data=TenantOut.model_validate(tenant), module=_M, msg_key="created",
                            code=tenant.tenant_code)


@router.get("/{ref}", response_model=ResponseModel[TenantOut])
async def get_tenant(_: PlatformAdmin, db: DBSession, ref: str):
    return ResponseModel.ok(data=TenantOut.model_validate(await service.get_tenant(db, ref)))


@router.patch("/{ref}", response_model=ResponseModel[TenantOut])
async def update_tenant(admin: PlatformAdmin, db: DBSession, ref: str, body: TenantUpdate):
    tenant = await service.update_tenant(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=TenantOut.model_validate(tenant), module=_M, msg_key="updated",
                            code=tenant.tenant_code)


@router.post("/{ref}/status", response_model=ResponseModel[TenantOut])
async def change_status(admin: PlatformAdmin, db: DBSession, ref: str, body: TenantStatusChange):
    tenant = await service.change_status(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=TenantOut.model_validate(tenant), module=_M, msg_key="status_changed",
                            code=tenant.tenant_code, status=tenant.status)
