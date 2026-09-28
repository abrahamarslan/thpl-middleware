"""RBAC business logic — role permission sets, assignments and the guardrails.

The guardrails (docs/rbac-module.md §4.8) are where an RBAC system becomes an
exploit if they are missing, so every path that changes who can do what goes
through here:

* **no privilege escalation** — to give a role (or a permission) to anyone, the actor
  must hold every permission involved, at a scope covering the target;
* **level check** — an actor may not grant a role above the highest level they hold;
  only ``rbac.owner:assign`` grants ``owner``;
* **never remove the last active owner** of an organization;
* **no editing your own grants**;
* a role defined in organization X may only be used within X's subtree (and a
  tenant-wide grant needs a role owned by a root organization);
* system roles' permission sets are code-owned (read-only through the API).

Services elsewhere are permission-agnostic — the HTTP edge decides (``rbac.deps``);
these functions take the actor's :class:`Grants` because the guardrails are about the
actor, not the route.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, ForbiddenError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.rbac import engine
from app.modules.rbac.catalogue import ALL_CODES, OWNER_ONLY
from app.modules.rbac.engine import Grants, Target
from app.modules.rbac.enums import AssignmentStatus, GrantMode, ScopeType
from app.modules.rbac.errors import RbacRuleError
from app.modules.rbac.model import Permission, RolePermission, UserRole
from app.modules.rbac.templates import RoleTemplate
from app.modules.roles.model import Role

logger = structlog.get_logger("app.rbac.service")


# ── permission sets ─────────────────────────────────────────────────────────

def computed_codes(role: Role) -> frozenset[str]:
    """The catalogue subset a COMPUTED role holds (empty for an explicit role)."""
    if role.grant_mode == GrantMode.ALL.value:
        return frozenset(ALL_CODES)
    if role.grant_mode == GrantMode.ALL_BUT_OWNER_ONLY.value:
        return frozenset(ALL_CODES - OWNER_ONLY)
    return frozenset()


async def role_codes(db: AsyncSession, roles: list[Role]) -> dict[int, list[str]]:
    """``{role_id: sorted permission codes}`` for many roles in one query."""
    explicit_ids = [r.id for r in roles if r.grant_mode == GrantMode.EXPLICIT.value]
    explicit = await engine._explicit_permissions(db, explicit_ids)   # noqa: SLF001 — same package
    return {
        r.id: sorted(explicit.get(r.id, frozenset()) if r.grant_mode == GrantMode.EXPLICIT.value
                     else computed_codes(r))
        for r in roles
    }


async def _permission_ids(db: AsyncSession, codes: set[str]) -> dict[str, int]:
    if not codes:
        return {}
    rows = await db.execute(
        select(Permission.permission_code, Permission.id).where(Permission.permission_code.in_(codes))
    )
    found = dict(rows.all())
    missing = codes - found.keys()
    if missing:
        # The catalogue row is missing (a fresh code the seeder has not inserted yet): insert-missing and retry.
        from app.modules.rbac.seed import ensure_permissions

        await ensure_permissions(db)
        rows = await db.execute(
            select(Permission.permission_code, Permission.id).where(Permission.permission_code.in_(codes))
        )
        found = dict(rows.all())
    return found


def validate_codes(codes: list[str]) -> set[str]:
    """Refuse unknown permission codes (a typo would otherwise be silently inert)."""
    unknown = sorted({c for c in codes if c not in ALL_CODES})
    if unknown:
        raise RbacRuleError(
            f"Unknown permission code(s): {', '.join(unknown)}",
            data={"unknown": unknown, "hint": "GET /api/permissions lists the catalogue"},
        )
    return set(codes)


async def _replace_rows(db: AsyncSession, role: Role, wanted: set[str], *, prune: bool) -> tuple[set[str], set[str]]:
    """Diff-apply ``wanted`` onto an explicit role's rows. Returns (added, removed)."""
    ids = await _permission_ids(db, wanted)
    current = {
        code: rp for code, rp in (await db.execute(
            select(Permission.permission_code, RolePermission)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(RolePermission.role_id == role.id)
        )).all()
    }
    added = wanted - current.keys()
    removed = (set(current) - wanted) if prune else set()
    for code in sorted(added):
        db.add(RolePermission(role_id=role.id, permission_id=ids[code], organization_id=role.organization_id,
                              tenant_id=role.tenant_id))
    for code in removed:
        await db.delete(current[code])
    await db.flush()
    return added, removed


async def apply_template(db: AsyncSession, role: Role, template: RoleTemplate, *, prune: bool = False) -> None:
    """Give a freshly seeded (or re-seeded) system role its template permissions — missing-only by default."""
    if template.grant_mode != GrantMode.EXPLICIT:
        return
    await _replace_rows(db, role, set(template.permissions), prune=prune)


# ── guardrails ──────────────────────────────────────────────────────────────

async def _check_can_grant(
    db: AsyncSession, grants: Grants, role: Role, codes: set[str], target: Target,
) -> None:
    """The actor may hand out ``codes`` (of ``role``) at ``target`` — escalation + level checks."""
    if grants.platform_admin:
        return
    if role.code == "owner" and role.is_system:
        await grants.require(db, "rbac.owner:assign", target)
    elif role.hierarchy_level > grants.max_level:
        raise ForbiddenError(
            f"Role '{role.code}' (level {role.hierarchy_level}) is above your own level ({grants.max_level})",
            data={"role": role.code},
        )
    lacking = []
    for code in sorted(codes):
        if not await grants.allows(db, code, target):
            lacking.append(code)
    if lacking:
        raise ForbiddenError(
            "You cannot grant permissions you do not hold at this scope",
            data={"missing": lacking[:25], "missing_count": len(lacking)},
        )


async def owners_of(db: AsyncSession, organization_id: int) -> set[int]:
    """Active users who hold an ``owner`` role OF this organization (base role or open assignment)."""
    from app.modules.users.model import User

    owner_role_ids = select(Role.id).where(Role.organization_id == organization_id, Role.code == "owner")
    live = (User.deleted_at.is_(None), User.is_deactivated.is_not(True), User.is_banned.is_not(True))
    base = set((await db.scalars(select(User.id).where(User.role_id.in_(owner_role_ids), *live))).all())
    assigned = set((await db.scalars(
        select(UserRole.user_id).where(
            UserRole.role_id.in_(owner_role_ids), UserRole.status == AssignmentStatus.ACTIVE.value,
            UserRole.valid_to.is_(None),
        )
    )).all())
    if assigned:
        assigned = set((await db.scalars(select(User.id).where(User.id.in_(assigned), *live))).all())
    return base | assigned


async def ensure_not_last_owner(db: AsyncSession, user: Any, *, what: str = "remove") -> None:
    """Refuse an action that would leave the user's organization without an active owner."""
    org_id = getattr(user, "organization_id", None)
    if org_id is None:
        return
    owners = await owners_of(db, org_id)
    if user.id in owners and len(owners) <= 1:
        raise RbacRuleError(
            f"Cannot {what} the last active owner of the organization; grant another user the owner role first",
            data={"organization_id": org_id},
        )


def _no_self_edit(actor: Any, user_id: int, grants: Grants) -> None:
    if actor.id == user_id and not grants.platform_admin:
        raise RbacRuleError("You cannot change your own roles; ask another administrator")


# ── roles: permission sets ──────────────────────────────────────────────────

async def set_role_permissions(
    db: AsyncSession, role: Role, codes: list[str], *, actor: Any, grants: Grants,
) -> Role:
    """Replace a CUSTOM role's whole permission set."""
    if role.is_system:
        raise RbacRuleError(
            f"'{role.code}' is a system role: its permissions are managed in code. "
            "Clone it into a custom role to change them.",
        )
    wanted = validate_codes(codes)
    current = (await role_codes(db, [role]))[role.id]
    added = wanted - set(current)
    await _check_can_grant(db, grants, role, added, Target(organization_id=role.organization_id))
    added, removed = await _replace_rows(db, role, wanted, prune=True)
    await db.flush()
    await record_activity(
        db, action="role_permissions_replaced", actor_id=actor.id, subject_type="Role", subject_id=role.id,
        changes={"added": sorted(added), "removed": sorted(removed)},
    )
    await engine.bump_epoch(role.tenant_id)
    return role


async def clone_role(
    db: AsyncSession, source: Role, *, code: str, name: str | None, organization_id: int,
    actor: Any, grants: Grants,
) -> Role:
    """A custom copy of any role (typically a system one) with an explicit permission set."""
    codes = set((await role_codes(db, [source]))[source.id])
    clone = Role(
        code=code, name=name or f"{source.name} (copy)", description=source.description,
        organization_id=organization_id, is_system=False, grant_mode=GrantMode.EXPLICIT.value,
        hierarchy_level=min(source.hierarchy_level, max(grants.max_level, 1)) if not grants.platform_admin
        else source.hierarchy_level,
    )
    await _check_can_grant(db, grants, clone, codes, Target(organization_id=organization_id))
    if clone.hierarchy_level >= 100:
        clone.hierarchy_level = 99                      # nothing but the seeded owner is level 100
    db.add(clone)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(f"Role code '{code}' already exists in this organization") from exc
    await _replace_rows(db, clone, codes, prune=False)
    await record_activity(
        db, action="role_cloned", actor_id=actor.id, subject_type="Role", subject_id=clone.id,
        changes={"after": {"code": code, "from": source.code, "permissions": len(codes)}},
    )
    return clone


# ── assignments ─────────────────────────────────────────────────────────────

async def _resolve_role(db: AsyncSession, ref: str | int) -> Role:
    from app.modules.roles import service as roles_service

    return await roles_service.get_role(db, str(ref))


async def _scope_org_path(db: AsyncSession, org_id: int) -> str:
    from app.modules.organizations.model import Organization

    path = await db.scalar(select(Organization.hierarchy_path).where(Organization.id == org_id))
    if path is None:
        raise NotFoundError(f"Organization {org_id} not found")
    return path


async def _role_usable_at(db: AsyncSession, role: Role, scope: ScopeType, scope_org_id: int | None) -> None:
    """A role owned by organization X is usable within X's subtree; tenant-wide needs a root-owned role."""
    from app.modules.organizations.model import Organization

    owner_org = await db.scalar(select(Organization).where(Organization.id == role.organization_id))
    if owner_org is None:
        raise NotFoundError("The role's organization no longer exists")
    if scope == ScopeType.TENANT:
        if owner_org.parent_id is not None:
            raise RbacRuleError(
                f"'{role.code}' belongs to '{owner_org.org_code}', which is not a root organization; "
                "a tenant-wide grant needs a role owned by a root organization",
            )
        return
    scope_path = await _scope_org_path(db, scope_org_id)          # type: ignore[arg-type]
    if not scope_path.startswith(owner_org.hierarchy_path):
        raise RbacRuleError(
            f"Role '{role.code}' is owned by '{owner_org.org_code}' and can only be used inside that "
            "organization's subtree",
            data={"role_organization": owner_org.org_code},
        )


async def assign_role(
    db: AsyncSession, *, actor: Any, grants: Grants, user_id: int, role_ref: str | int,
    scope: ScopeType, organization_id: int | None, department_id: int | None, team_id: int | None,
    include_descendants: bool, valid_from: dt.datetime | None, valid_to: dt.datetime | None,
    reason: str | None,
) -> UserRole:
    from app.modules.users import crud as users_crud

    _no_self_edit(actor, user_id, grants)
    user = await users_crud.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    role = await _resolve_role(db, role_ref)
    if role.status != "active" or not role.is_assignable:
        raise RbacRuleError(f"Role '{role.code}' cannot be assigned (inactive, deprecated or not assignable)")

    # Resolve the scope anchor. Department/team scopes carry their own organization.
    scope_org = organization_id
    if scope == ScopeType.DEPARTMENT:
        from app.modules.teams.model import Department

        dept = await db.scalar(select(Department).where(Department.id == department_id))
        if dept is None:
            raise NotFoundError(f"Department {department_id} not found")
        scope_org = dept.organization_id
    elif scope == ScopeType.TEAM:
        from app.modules.teams.model import Team

        team = await db.scalar(select(Team).where(Team.id == team_id))
        if team is None:
            raise NotFoundError(f"Team {team_id} not found")
        scope_org = team.organization_id
    elif scope == ScopeType.ORGANIZATION and scope_org is None:
        raise RbacRuleError("An organization-scoped assignment needs an organization")
    if scope == ScopeType.TENANT:
        scope_org = None

    await _role_usable_at(db, role, scope, scope_org)
    target = Target(organization_id=scope_org, department_id=department_id, team_id=team_id)
    codes = set((await role_codes(db, [role]))[role.id])
    await _check_can_grant(db, grants, role, codes, target)

    row = UserRole(
        user_id=user.id, role_id=role.id, scope_type=scope.value, organization_id=scope_org,
        department_id=department_id if scope == ScopeType.DEPARTMENT else None,
        team_id=team_id if scope == ScopeType.TEAM else None,
        include_descendants=include_descendants, valid_to=valid_to, reason=reason,
        tenant_id=user.tenant_id,
    )
    if valid_from:
        row.valid_from = valid_from
    holder, role_code = user.email, role.code            # read now: a failed flush expires the instances
    try:
        # The row is added INSIDE the savepoint: ``begin_nested`` autoflushes what is pending BEFORE it opens
        # the savepoint, so a row added earlier would fail outside it and poison the whole transaction.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"{holder} already holds '{role_code}' at this scope",
            data={"role": role_code, "scope": scope.value},
        ) from exc
    await record_activity(
        db, action="role_assigned", actor_id=actor.id, subject_type="User", subject_id=user.id,
        changes={"after": {"role": role.code, "scope": scope.value, "organization_id": scope_org,
                           "department_id": row.department_id, "team_id": row.team_id,
                           "valid_to": valid_to.isoformat() if valid_to else None}},
        context={"reason": reason},
    )
    await engine.forget_user(user.tenant_id, user.id)
    return row


async def list_assignments(db: AsyncSession, user_id: int) -> list[UserRole]:
    return list((await db.scalars(
        select(UserRole).where(UserRole.user_id == user_id).order_by(UserRole.created_at.desc())
    )).all())


async def revoke_assignment(
    db: AsyncSession, *, actor: Any, grants: Grants, user_id: int, assignment_ref: str, reason: str,
) -> None:
    import uuid as uuid_lib

    _no_self_edit(actor, user_id, grants)
    try:
        cond = UserRole.uuid == uuid_lib.UUID(str(assignment_ref))
    except ValueError:
        cond = UserRole.id == int(assignment_ref) if str(assignment_ref).isdigit() else None
    if cond is None:
        raise NotFoundError(f"Assignment '{assignment_ref}' not found")
    row = await db.scalar(select(UserRole).where(cond, UserRole.user_id == user_id))
    if row is None:
        raise NotFoundError(f"Assignment '{assignment_ref}' not found")
    role = await db.scalar(select(Role).where(Role.id == row.role_id))
    if role is not None:
        # Revoking is granting's mirror: you may only take away what you could hand out.
        codes = set((await role_codes(db, [role]))[role.id])
        await _check_can_grant(db, grants, role, codes, Target(
            organization_id=row.organization_id, department_id=row.department_id, team_id=row.team_id))
        if role.code == "owner" and role.is_system:
            from app.modules.users.model import User

            user = await db.scalar(select(User).where(User.id == user_id))
            if user is not None:
                await ensure_not_last_owner(db, user, what="revoke the owner role of")
    row.status = AssignmentStatus.REVOKED.value
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await record_activity(
        db, action="role_revoked", actor_id=actor.id, subject_type="User", subject_id=user_id,
        changes={"before": {"role_id": row.role_id, "scope": row.scope_type}}, context={"reason": reason},
    )
    await engine.forget_user(row.tenant_id, user_id)


async def set_base_role(
    db: AsyncSession, *, actor: Any, grants: Grants, user: Any, role_ref: str | int | None,
) -> Any:
    """Change ``users.role_id``. The role must be one of the USER's organization (composite FK)."""
    _no_self_edit(actor, user.id, grants)
    if role_ref is None:
        raise RbacRuleError("A base role is required; use a low-privilege role such as 'member'")
    role = await _resolve_role(db, role_ref)
    if role.organization_id != user.organization_id:
        raise RbacRuleError(
            "A base role must be a role of the user's own organization; use a contextual assignment "
            "to give a role owned by another organization",
            data={"user_organization_id": user.organization_id, "role_organization_id": role.organization_id},
        )
    if role.status != "active" or not role.is_assignable:
        raise RbacRuleError(f"Role '{role.code}' cannot be assigned (inactive, deprecated or not assignable)")
    current = await db.scalar(select(Role).where(Role.id == user.role_id)) if user.role_id else None
    if current is not None and current.code == "owner" and current.is_system and role.code != "owner":
        await ensure_not_last_owner(db, user, what="demote")
    codes = set((await role_codes(db, [role]))[role.id])
    await _check_can_grant(db, grants, role, codes, Target(organization_id=user.organization_id))
    before = user.role_id
    user.role_id = role.id
    await db.flush()
    await record_activity(
        db, action="base_role_changed", actor_id=actor.id, subject_type="User", subject_id=user.id,
        changes={"before": {"role_id": before}, "after": {"role_id": role.id, "role": role.code}},
    )
    await engine.forget_user(user.tenant_id, user.id)
    return user


# ── defaults & bootstrap (no actor: system paths) ───────────────────────────

async def default_role_id(db: AsyncSession, *, tenant_id: int, organization_id: int, code: str = "member") -> int | None:
    """The system role a new user of an organization gets (``member``). ``None`` if not seeded."""
    role_id = await db.scalar(
        select(Role.id).where(Role.tenant_id == tenant_id, Role.organization_id == organization_id,
                              Role.code == code)
        .execution_options(all_tenants=True)
    )
    if role_id is None:
        logger.warning("rbac_default_role_missing", tenant_id=tenant_id, organization_id=organization_id, code=code)
    return role_id


async def ensure_tenant_owner(db: AsyncSession, user: Any, owner_role: Role) -> UserRole | None:
    """Give a user the tenant-wide ``owner`` grant (used when a tenant is bootstrapped).

    The base role covers the home organization's subtree; this grant adds the WHOLE tenant —
    including creating new root organizations — which is what "administrator of the tenant" means.
    """
    existing = await db.scalar(select(UserRole).where(
        UserRole.user_id == user.id, UserRole.role_id == owner_role.id,
        UserRole.scope_type == ScopeType.TENANT.value, UserRole.status == AssignmentStatus.ACTIVE.value,
        UserRole.valid_to.is_(None),
    ))
    if existing is not None:
        return existing
    row = UserRole(
        user_id=user.id, role_id=owner_role.id, scope_type=ScopeType.TENANT.value, organization_id=None,
        include_descendants=True, reason="tenant bootstrap", tenant_id=user.tenant_id,
    )
    db.add(row)
    await db.flush()
    await engine.forget_user(user.tenant_id, user.id)
    return row


__all__ = [
    "apply_template", "assign_role", "clone_role", "computed_codes", "default_role_id",
    "ensure_not_last_owner", "ensure_tenant_owner", "list_assignments", "owners_of",
    "revoke_assignment", "role_codes", "set_base_role", "set_role_permissions", "validate_codes",
]
