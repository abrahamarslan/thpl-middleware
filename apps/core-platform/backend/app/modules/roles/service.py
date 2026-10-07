"""Roles business logic — organization-scoped (inside the caller's tenant).

What a role may DO lives in ``rbac`` (``role_permissions`` rows for explicit roles, computed
modes for ``owner``/``admin``); this module owns the role rows themselves and seeds each
organization's system roles from ``rbac.templates``.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.database.tenancy import current_organization_id, current_tenant_id
from app.modules.activity.recorder import record_activity
from app.modules.rbac import engine
from app.modules.rbac import service as rbac
from app.modules.rbac.engine import Grants, Target
from app.modules.rbac.enums import GrantMode
from app.modules.rbac.templates import ROLE_TEMPLATES
from app.modules.roles.model import Role
from app.modules.roles.schema import RoleCreate, RoleUpdate


class RoleRuleError(AppError):
    status_code = 422
    code = "role_rule_violation"


async def list_roles(db: AsyncSession) -> list[Role]:
    return list((await db.scalars(select(Role).order_by(Role.is_system.desc(), Role.hierarchy_level.desc(), Role.code))).all())


async def get_role(db: AsyncSession, ref: str) -> Role:
    """By id, or by code. A code exists once PER ORGANIZATION (every organization has an ``admin``), so it is
    resolved in the request's organization when one is bound — never to whichever sibling's role matches first."""
    if str(ref).isdigit():
        cond = Role.id == int(ref)
    else:
        cond = Role.code == str(ref)
        organization_id = current_organization_id()
        if organization_id is not None:
            cond = cond & (Role.organization_id == organization_id)
    role = await db.scalar(select(Role).where(cond).order_by(Role.id).limit(1))
    if role is None:
        raise NotFoundError(f"Role '{ref}' not found")
    return role


def _require_org() -> int:
    organization_id = current_organization_id()
    if organization_id is None:
        raise RoleRuleError(
            "No organization is bound to this request; choose one with the 'X-Organization-Code' header.",
            data={"hint": "GET /api/organizations lists them"},
        )
    return organization_id


async def create_role(
    db: AsyncSession, body: RoleCreate, *, actor: Any, grants: Grants, organization_id: int | None = None,
) -> Role:
    organization_id = organization_id or _require_org()
    if await db.scalar(select(Role.id).where(
        Role.organization_id == organization_id, func.lower(Role.code) == body.code.lower()
    )):
        raise ConflictError(f"Role code '{body.code}' already exists in this organization")
    codes = rbac.validate_codes(body.permissions)
    role = Role(
        code=body.code, name=body.name, description=body.description, hierarchy_level=body.hierarchy_level,
        organization_id=organization_id, grant_mode=GrantMode.EXPLICIT.value, is_system=False,
    )
    # Escalation guard: you cannot mint a role stronger than you are.
    await rbac._check_can_grant(db, grants, role, codes, Target(organization_id=organization_id))  # noqa: SLF001
    db.add(role)
    await db.flush()
    await rbac._replace_rows(db, role, codes, prune=False)  # noqa: SLF001
    await record_activity(db, action="role_created", actor_id=actor.id, subject_type="Role", subject_id=role.id,
                          changes={"after": {"code": role.code, "level": role.hierarchy_level,
                                             "permissions": sorted(codes)}})
    return role


async def update_role(db: AsyncSession, ref: str, body: RoleUpdate, *, actor: Any) -> Role:
    role = await get_role(db, ref)
    if role.row_version != body.row_version:
        raise ConflictError(f"Role '{role.code}' changed since you loaded it; reload and retry",
                            data={"current_row_version": role.row_version})
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if role.is_system and {"status", "hierarchy_level", "is_assignable"} & changes.keys():
        raise RoleRuleError(f"'{role.code}' is a system role: its status, level and assignability are code-owned")
    for field, value in changes.items():
        setattr(role, field, value)
    await db.flush()
    await record_activity(db, action="role_updated", actor_id=actor.id, subject_type="Role", subject_id=role.id,
                          changes={"after": changes})
    if {"status", "hierarchy_level", "is_assignable"} & changes.keys():
        await engine.bump_epoch(role.tenant_id)
    return role


async def delete_role(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> None:
    from app.modules.rbac.model import UserRole
    from app.modules.teams.model import TeamRole
    from app.modules.users.model import User

    role = await get_role(db, ref)
    if role.is_system:
        raise RoleRuleError(f"'{role.code}' is a system role and cannot be deleted")
    holders = await db.scalar(select(func.count()).select_from(User).where(
        User.role_id == role.id, User.organization_id == role.organization_id
    ))
    if holders:
        raise RoleRuleError(f"{holders} user(s) still hold role '{role.code}'; reassign them first")
    assigned = await db.scalar(select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id))
    if assigned:
        raise RoleRuleError(f"{assigned} assignment(s) still use role '{role.code}'; revoke them first")
    mapped = await db.scalar(select(func.count()).select_from(TeamRole).where(TeamRole.rbac_role_id == role.id))
    if mapped:
        raise RoleRuleError(f"{mapped} team role(s) still map to role '{role.code}'; unmap them first")
    role.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await record_activity(db, action="role_deleted", actor_id=actor.id, subject_type="Role", subject_id=role.id,
                          context={"reason": reason})
    await engine.bump_epoch(role.tenant_id)


async def seed_system_roles(db: AsyncSession, organization_id: int, *, prune: bool = False) -> list[Role]:
    """Idempotent: create the missing system roles for one organization and give explicit ones their permissions.

    ``owner`` and ``admin`` carry no permission rows (computed grant modes). The others get their
    template's permissions ADDED if missing; nothing an operator removed is put back unless
    ``prune`` re-syncs the set exactly.
    """
    from app.modules.rbac.seed import ensure_permissions

    await ensure_permissions(db)
    existing = {
        role.code: role for role in (await db.scalars(select(Role).where(Role.organization_id == organization_id))).all()
    }
    created: list[Role] = []
    for template in ROLE_TEMPLATES:
        role = existing.get(template.code)
        if role is None:
            role = Role(
                code=template.code, name=template.name, description=template.description, is_system=True,
                organization_id=organization_id, grant_mode=template.grant_mode.value,
                hierarchy_level=template.level,
            )
            db.add(role)
            created.append(role)
        elif role.is_system:
            role.grant_mode = template.grant_mode.value
            role.hierarchy_level = template.level
    await db.flush()
    for template in ROLE_TEMPLATES:
        role = next((r for r in created if r.code == template.code), None) or existing.get(template.code)
        if role is not None and role.is_system:
            await rbac.apply_template(db, role, template, prune=prune)
    return created


async def _org_roles(db: AsyncSession, organization_id: int) -> list[Role]:
    return list((await db.scalars(
        select(Role).where(Role.organization_id == organization_id)
        .order_by(Role.hierarchy_level.desc(), Role.code)
    )).all())


async def resync_system_roles(db: AsyncSession, *, prune: bool = False, actor: Any) -> list[Role]:
    """Re-apply the code-owned templates to THIS organization's system roles.

    A release can add a permission to a template (e.g. ``fieldops.field_work:use`` on ``member``);
    an organization seeded before it must be re-synced. Add-missing-only by default, so a permission
    an operator deliberately removed is NOT put back; ``prune=True`` makes each explicit system
    role's set exactly match its template. Grants are cached per tenant, so the epoch is bumped.
    """
    organization_id = _require_org()
    before = await rbac.role_codes(db, await _org_roles(db, organization_id))
    await seed_system_roles(db, organization_id, prune=prune)
    await db.flush()
    roles = await _org_roles(db, organization_id)
    after = await rbac.role_codes(db, roles)
    added = {r.code: sorted(set(after[r.id]) - set(before.get(r.id, ()))) for r in roles}
    removed = {r.code: sorted(set(before.get(r.id, ())) - set(after[r.id])) for r in roles}
    await record_activity(
        db, action="roles_resynced", actor_id=actor.id, subject_type="Organization", subject_id=organization_id,
        changes={"added": {c: v for c, v in added.items() if v},
                 "removed": {c: v for c, v in removed.items() if v}},
        context={"prune": prune},
    )
    await engine.bump_epoch(current_tenant_id())
    return roles
