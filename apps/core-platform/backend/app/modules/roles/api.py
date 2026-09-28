"""Roles API — mounted at /api/roles (the caller's tenant only).

| Route | Permission |
|---|---|
| ``GET ""`` · ``GET /{ref}`` | any signed-in user |
| ``POST ""`` | ``rbac.role:create`` |
| ``PATCH /{ref}`` | ``rbac.role:update`` (at the role's organization) |
| ``PUT /{ref}/permissions`` | ``rbac.role:manage`` — a CUSTOM role's whole permission set |
| ``POST /{ref}/clone`` | ``rbac.role:create`` — a custom copy of any role |
| ``DELETE /{ref}?reason=`` | ``rbac.role:delete`` |

``{ref}`` = role id or code. System roles (owner, admin, member, …) are seeded per organization from
``rbac.templates``; their permission sets are code-owned, so they are read-only here (clone one to change it).
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.rbac import service as rbac
from app.modules.rbac.deps import GrantsDep, Perm
from app.modules.roles import service
from app.modules.roles.deps import role_target
from app.modules.roles.model import Role
from app.modules.roles.schema import (
    RoleClone,
    RoleCreate,
    RoleOut,
    RolePermissionsReplace,
    RoleUpdate,
)
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "roles"


async def _outs(db, roles: list[Role]) -> list[RoleOut]:
    codes = await rbac.role_codes(db, roles)
    out = []
    for role in roles:
        item = RoleOut.model_validate(role)
        item.permissions = codes.get(role.id, [])
        out.append(item)
    return out


@router.get("", response_model=ResponseModel[list[RoleOut]])
async def list_roles(_: CurrentUser, db: DBSession):
    return ResponseModel.ok(data=await _outs(db, await service.list_roles(db)))


@router.get("/{ref}", response_model=ResponseModel[RoleOut])
async def get_role(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=(await _outs(db, [await service.get_role(db, ref)]))[0])


@router.post("", response_model=ResponseModel[RoleOut], status_code=201)
async def create_role(actor: Perm("rbac.role:create"), grants: GrantsDep, db: DBSession, body: RoleCreate):
    role = await service.create_role(db, body, actor=actor, grants=grants)
    return ResponseModel.ok(data=(await _outs(db, [role]))[0], module=_M, msg_key="created", code=role.code)


@router.patch("/{ref}", response_model=ResponseModel[RoleOut])
async def update_role(
    actor: Perm("rbac.role:update", target=role_target), db: DBSession, ref: str, body: RoleUpdate,
):
    role = await service.update_role(db, ref, body, actor=actor)
    return ResponseModel.ok(data=(await _outs(db, [role]))[0], module=_M, msg_key="updated", code=role.code)


@router.put("/{ref}/permissions", response_model=ResponseModel[RoleOut])
async def replace_role_permissions(
    actor: Perm("rbac.role:manage", target=role_target), grants: GrantsDep, db: DBSession,
    ref: str, body: RolePermissionsReplace,
):
    """Replace a custom role's permission set. Unknown codes are refused; you cannot add a permission you lack."""
    role = await service.get_role(db, ref)
    if role.row_version != body.row_version:
        from app.common.exception.errors import ConflictError

        raise ConflictError(f"Role '{role.code}' changed since you loaded it; reload and retry",
                            data={"current_row_version": role.row_version})
    role = await rbac.set_role_permissions(db, role, body.permissions, actor=actor, grants=grants)
    return ResponseModel.ok(data=(await _outs(db, [role]))[0], module="rbac", msg_key="permissions_replaced",
                            code=role.code)


@router.post("/{ref}/clone", response_model=ResponseModel[RoleOut], status_code=201)
async def clone_role(
    actor: Perm("rbac.role:create", target=role_target), grants: GrantsDep, db: DBSession,
    ref: str, body: RoleClone,
):
    """A custom copy (explicit permission set) of any role — the way to customise a system role."""
    from app.database.tenancy import current_organization_id

    source = await service.get_role(db, ref)
    organization_id = current_organization_id() or source.organization_id
    if body.organization:
        from app.modules.organizations import service as orgs

        organization_id = (await orgs.get_organization(db, body.organization)).id
    clone = await rbac.clone_role(
        db, source, code=body.code, name=body.name, organization_id=organization_id, actor=actor, grants=grants,
    )
    return ResponseModel.ok(data=(await _outs(db, [clone]))[0], module="rbac", msg_key="role_cloned",
                            code=clone.code, source=source.code)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_role(
    actor: Perm("rbac.role:delete", target=role_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    await service.delete_role(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
