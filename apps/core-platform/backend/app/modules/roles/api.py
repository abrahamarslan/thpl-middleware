"""Roles API — mounted at /api/roles (the caller's tenant only).

| Route | Who |
|---|---|
| ``GET ""`` · ``GET /{ref}`` | member |
| ``POST ""`` · ``PATCH /{ref}`` · ``DELETE /{ref}?reason=`` | tenant admin |

``{ref}`` = role id or code. System roles (owner, admin, member) are seeded
per tenant and cannot be deleted.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.roles import service
from app.modules.roles.schema import RoleCreate, RoleOut, RoleUpdate
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "roles"


@router.get("", response_model=ResponseModel[list[RoleOut]])
async def list_roles(_: CurrentUser, db: DBSession):
    return ResponseModel.ok(data=[RoleOut.model_validate(r) for r in await service.list_roles(db)])


@router.get("/{ref}", response_model=ResponseModel[RoleOut])
async def get_role(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=RoleOut.model_validate(await service.get_role(db, ref)))


@router.post("", response_model=ResponseModel[RoleOut], status_code=201)
async def create_role(admin: TenantAdmin, db: DBSession, body: RoleCreate):
    role = await service.create_role(db, body, actor_id=admin.id)
    return ResponseModel.ok(data=RoleOut.model_validate(role), module=_M, msg_key="created", code=role.code)


@router.patch("/{ref}", response_model=ResponseModel[RoleOut])
async def update_role(admin: TenantAdmin, db: DBSession, ref: str, body: RoleUpdate):
    role = await service.update_role(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=RoleOut.model_validate(role), module=_M, msg_key="updated", code=role.code)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_role(admin: TenantAdmin, db: DBSession, ref: str,
                      reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_role(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
