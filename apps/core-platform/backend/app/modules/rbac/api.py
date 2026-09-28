"""RBAC HTTP API.

| Route | Permission |
|---|---|
| ``GET /api/permissions`` | ``rbac.permission:read`` — the catalogue, grouped by module |
| ``GET /api/me/permissions`` | any signed-in user — effective grants, for the UI |
| ``GET /api/users/{id}/roles`` | ``rbac.assignment:read`` |
| ``POST /api/users/{id}/roles`` | ``rbac.assignment:assign`` (+ the escalation/level guardrails) |
| ``DELETE /api/users/{id}/roles/{assignment}?reason=`` | ``rbac.assignment:assign`` |
| ``PUT /api/users/{id}/base-role`` | ``users.user:assign_role`` (+ guardrails) |

Role CRUD and role permission sets live with roles (``/api/roles``).
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.rbac import service
from app.modules.rbac.catalogue import PERMISSIONS
from app.modules.rbac.deps import GrantsDep, Perm
from app.modules.rbac.enums import ScopeType
from app.modules.rbac.schema import (
    BaseRoleSet,
    GrantOut,
    MyPermissionsOut,
    PermissionGroupOut,
    PermissionOut,
    UserRoleCreate,
    UserRoleOut,
)
from app.modules.roles.model import Role
from app.modules.users.deps import CurrentUser

permissions_router = APIRouter()
me_router = APIRouter()
user_roles_router = APIRouter()
_M = "rbac"


@permissions_router.get("", response_model=ResponseModel[list[PermissionGroupOut]])
async def list_permissions(_: Perm("rbac.permission:read")):
    """Every permission that can be granted, grouped by module."""
    groups: dict[str, list[PermissionOut]] = {}
    for p in PERMISSIONS.values():
        groups.setdefault(p.module, []).append(PermissionOut(
            code=p.code, module=p.module, resource=p.resource, action=p.action,
            description=p.description or None, owner_only=p.owner_only,
        ))
    return ResponseModel.ok(data=[PermissionGroupOut(module=m, permissions=ps) for m, ps in groups.items()])


@me_router.get("/permissions", response_model=ResponseModel[MyPermissionsOut])
async def my_permissions(_: CurrentUser, grants: GrantsDep):
    """What the signed-in user may do, per grant. For gating UI — never rely on it to authorize."""
    summary = grants.summary()
    every = sorted({c for g in summary["grants"] for c in g["permissions"]})
    return ResponseModel.ok(data=MyPermissionsOut(
        platform_admin=summary["platform_admin"],
        grants=[GrantOut(**g) for g in summary["grants"]],
        permissions=every,
    ))


async def _out(db, rows) -> list[UserRoleOut]:
    codes = dict((await db.execute(
        select(Role.id, Role.code).where(Role.id.in_({r.role_id for r in rows}))
    )).all()) if rows else {}
    out = []
    for r in rows:
        item = UserRoleOut.model_validate(r)
        item.role_code = codes.get(r.role_id)
        out.append(item)
    return out


async def _require_user(db, user_id: int):
    from app.modules.users import service as users_service

    return await users_service.get_user(db, user_id)


@user_roles_router.get("/{user_id}/roles", response_model=ResponseModel[list[UserRoleOut]])
async def list_user_roles(_: Perm("rbac.assignment:read"), db: DBSession, user_id: int):
    await _require_user(db, user_id)
    return ResponseModel.ok(data=await _out(db, await service.list_assignments(db, user_id)))


@user_roles_router.post("/{user_id}/roles", response_model=ResponseModel[UserRoleOut], status_code=201)
async def assign_user_role(
    actor: Perm("rbac.assignment:assign"), grants: GrantsDep, db: DBSession, user_id: int, body: UserRoleCreate,
):
    """Grant a role to a user at a tenant / organization / department / team scope."""
    organization_id = None
    if body.scope_type == ScopeType.ORGANIZATION:
        from app.modules.organizations import service as orgs

        organization_id = (await orgs.get_organization(db, body.organization)).id
    row = await service.assign_role(
        db, actor=actor, grants=grants, user_id=user_id, role_ref=body.role, scope=body.scope_type,
        organization_id=organization_id, department_id=body.department_id, team_id=body.team_id,
        include_descendants=body.include_descendants, valid_from=body.valid_from, valid_to=body.valid_to,
        reason=body.reason,
    )
    return ResponseModel.ok(data=(await _out(db, [row]))[0], module=_M, msg_key="role_assigned")


@user_roles_router.delete("/{user_id}/roles/{assignment_ref}", response_model=ResponseModel[None])
async def revoke_user_role(
    actor: Perm("rbac.assignment:assign"), grants: GrantsDep, db: DBSession, user_id: int, assignment_ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    await service.revoke_assignment(
        db, actor=actor, grants=grants, user_id=user_id, assignment_ref=assignment_ref, reason=reason,
    )
    return ResponseModel.ok(data=None, module=_M, msg_key="role_revoked")


@user_roles_router.put("/{user_id}/base-role", response_model=ResponseModel[dict])
async def set_base_role(
    actor: Perm("users.user:assign_role"), grants: GrantsDep, db: DBSession, user_id: int, body: BaseRoleSet,
):
    """Change ``users.role_id`` — the role must belong to the user's own organization."""
    user = await _require_user(db, user_id)
    user = await service.set_base_role(db, actor=actor, grants=grants, user=user, role_ref=body.role)
    return ResponseModel.ok(data={"user_id": user.id, "role_id": user.role_id}, module=_M, msg_key="base_role_changed")


__all__ = ["me_router", "permissions_router", "user_roles_router"]
