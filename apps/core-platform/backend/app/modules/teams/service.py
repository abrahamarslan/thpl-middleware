"""Teams business logic — departments, job titles, team types/roles, teams and memberships.

Rules worth knowing (docs/rbac-module.md §5):

* Trees (departments, team types, teams) keep ``_lft/_rgt/depth/path`` through ONE routine,
  ``app.common.tree.recompute_bounds``, run as a full recompute under a per-(tree, organization)
  advisory lock — exactly ``categories``. Cycles are refused there (``TreeError``) and by CHECKs.
* A parent must be in the SAME organization (the composite FK enforces it; the service says so first).
* A membership grants nothing until approved, active and in window; leaving closes ``valid_until``
  and rejoining inserts a new row. Nobody approves their own membership.
* A team role that maps to an RBAC role can only be attached by someone who holds that role's
  permissions at the team (no privilege escalation through a team).
* Permission checks are the ROUTES' business (``rbac.deps.Perm``); this module holds the rules.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import bindparam, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.ext.asyncio import AsyncSession

from app.common import tree
from app.common.exception.errors import ConflictError, ForbiddenError, NotFoundError
from app.common.serialization import to_jsonable
from app.database.tenancy import current_organization_id
from app.modules.activity.recorder import record_activity
from app.modules.rbac import engine
from app.modules.rbac.engine import Grants, Target
from app.modules.teams.enums import ApprovalStatus, MembershipStatus, TeamStatus
from app.modules.teams.model import Department, JobTitle, Team, TeamRole, TeamType, UserTeam
from app.modules.teams.scope import TeamsRuleError, require_organization

logger = structlog.get_logger("app.teams")

#: Cap on one bulk request (docs/rbac-module.md §4.10).
BULK_LIMIT = 200


# ── generic helpers ─────────────────────────────────────────────────────────

def _by_ref(model: Any, ref: str | int, code_col: Any):
    """uuid (preferred) | numeric id | code. A code is looked up in the request's organization when one is bound."""
    text_ref = str(ref)
    try:
        return model.uuid == uuid_lib.UUID(text_ref)
    except ValueError:
        pass
    if text_ref.isdigit():
        return model.id == int(text_ref)
    cond = func.lower(code_col) == text_ref.lower()
    org = current_organization_id()
    return cond & (model.organization_id == org) if org is not None else cond


async def _get(db: AsyncSession, model: Any, ref: str | int, code_col: Any, label: str):
    row = await db.scalar(select(model).where(_by_ref(model, ref, code_col)).limit(1))
    if row is None:
        raise NotFoundError(f"{label} '{ref}' not found")
    return row


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


async def _ensure_code_free(
    db: AsyncSession, model: Any, code_col: Any, organization_id: int, code: str,
    *, except_id: int | None = None, extra: tuple = (), label: str = "Code",
) -> None:
    stmt = select(model.id).where(model.organization_id == organization_id,
                                  func.lower(code_col) == code.lower(), *extra)
    if except_id is not None:
        stmt = stmt.where(model.id != except_id)
    if await db.scalar(stmt.limit(1)):
        raise ConflictError(f"{label} '{code}' is already used in this organization")


async def _apply(db: AsyncSession, row: Any, changes: dict[str, Any], *, action: str, subject: str, actor: Any) -> None:
    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    await db.flush()
    await record_activity(
        db, action=action, actor_id=actor.id, subject_type=subject, subject_id=row.id,
        changes={"before": to_jsonable(before), "after": to_jsonable(changes)},
    )


async def _existing_user(db: AsyncSession, user_id: int) -> Any:
    from app.modules.users import crud as users_crud

    user = await users_crud.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


async def _paginate(db: AsyncSession, stmt: Any, page: int, page_size: int) -> tuple[list[Any], int]:
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = (await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return list(rows), total


# ── trees ───────────────────────────────────────────────────────────────────

@dataclass
class _Node:
    """A plain stand-in for a tree row: ``recompute_bounds`` runs on these, never on ORM instances, so
    computing the layout cannot dirty (and version-bump) a row."""

    id: int
    parent_id: int | None
    slug: str
    position: int
    depth: int = 0
    lft: int = 0
    rgt: int = 0
    path: str | None = None
    is_root: bool = True


async def _recompute(db: AsyncSession, model: Any, kind: str, tenant_id: int, organization_id: int) -> None:
    """The ONLY writer of a tree's bounds — full recompute under the tree's lock."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{kind}_tree:{tenant_id}:{organization_id}"},
    )
    rows = list((await db.scalars(
        select(model).where(model.organization_id == organization_id).order_by(model.position, model.id)
    )).all())
    nodes = {r.id: _Node(r.id, r.parent_id, r.slug, r.position) for r in rows}
    try:
        tree.recompute_bounds(list(nodes.values()))
    except tree.TreeError as exc:
        raise TeamsRuleError(str(exc)) from exc

    # The bounds/depth/path are DERIVED, not edited: write them with a Core UPDATE that leaves ``row_version``
    # alone, so adding a sibling never makes a client's copy of some other node "stale" (409 on its next edit).
    changed = [
        {"b_id": r.id, "b_lft": n.lft, "b_rgt": n.rgt, "b_depth": n.depth, "b_path": n.path, "b_root": n.is_root}
        for r in rows if (n := nodes[r.id]) and (
            (r.lft, r.rgt, r.depth, r.path, r.is_root) != (n.lft, n.rgt, n.depth, n.path, n.is_root))
    ]
    if changed:
        table = model.__table__          # Core, not the ORM: an ORM bulk UPDATE would demand (and bump) row_version
        await db.execute(
            update(table).where(table.c.id == bindparam("b_id"))
            .values({"_lft": bindparam("b_lft"), "_rgt": bindparam("b_rgt"), "depth": bindparam("b_depth"),
                     "path": bindparam("b_path"), "is_root": bindparam("b_root")}),
            changed,
        )
        for r in rows:                                    # keep the loaded instances in step, without marking them dirty
            n = nodes[r.id]
            for attr, value in (("lft", n.lft), ("rgt", n.rgt), ("depth", n.depth), ("path", n.path),
                                ("is_root", n.is_root)):
                set_committed_value(r, attr, value)
    # Department / team scoped grants are cached as expanded id sets: a tree change invalidates them.
    await engine.bump_epoch(tenant_id)


async def _resolve_parent(
    db: AsyncSession, model: Any, code_col: Any, ref: str | None, organization_id: int, label: str,
) -> Any | None:
    if ref is None or ref == "":
        return None
    parent = await _get(db, model, ref, code_col, f"Parent {label}")
    if parent.organization_id != organization_id:
        raise TeamsRuleError(
            f"A {label} can only sit under a {label} of the SAME organization",
            data={"parent_organization_id": parent.organization_id, "organization_id": organization_id},
        )
    return parent


def _refuse_cycle(node: Any, parent: Any | None, label: str) -> None:
    if parent is None:
        return
    if parent.id == node.id or (node.lft <= parent.lft and parent.rgt <= node.rgt and node.rgt > node.lft):
        raise TeamsRuleError(f"A {label} cannot be moved under itself or one of its descendants")


def build_tree(nodes: list[Any], *, code: str, name: str) -> list[dict[str, Any]]:
    """Nested ``{id, uuid, code, name, depth, status, children}`` from a flat, lft-ordered list."""
    by_id = {n.id: {"id": n.id, "uuid": n.uuid, "code": getattr(n, code), "name": getattr(n, name),
                    "depth": n.depth, "status": n.status, "children": []} for n in nodes}
    roots: list[dict[str, Any]] = []
    for n in nodes:
        item = by_id[n.id]
        parent = by_id.get(n.parent_id) if n.parent_id else None
        (parent["children"] if parent else roots).append(item)
    return roots


async def _tree_rows(db: AsyncSession, model: Any, organization: int | None) -> list[Any]:
    stmt = select(model).order_by(model.organization_id, model.lft, model.id)
    if organization is not None:
        stmt = stmt.where(model.organization_id == organization)
    return list((await db.scalars(stmt)).all())


async def _subtree(db: AsyncSession, model: Any, node: Any, *, include_self: bool = False) -> list[Any]:
    stmt = select(model).where(model.organization_id == node.organization_id,
                               model.lft >= node.lft, model.rgt <= node.rgt).order_by(model.lft)
    if not include_self:
        stmt = stmt.where(model.id != node.id)
    return list((await db.scalars(stmt)).all())


# ── departments ─────────────────────────────────────────────────────────────

async def get_department(db: AsyncSession, ref: str | int) -> Department:
    return await _get(db, Department, ref, Department.department_code, "Department")


async def list_departments(
    db: AsyncSession, *, q: str | None, status: str | None, organization: int | None, parent: str | None,
    page: int, page_size: int,
) -> tuple[list[Department], int]:
    stmt = select(Department).order_by(Department.organization_id, Department.lft, Department.id)
    if organization is not None:
        stmt = stmt.where(Department.organization_id == organization)
    if status:
        stmt = stmt.where(Department.status == status)
    if q:
        stmt = stmt.where(Department.department_name.ilike(f"%{q.strip()}%")
                          | Department.department_code.ilike(f"%{q.strip()}%"))
    if parent is not None:
        stmt = stmt.where(Department.parent_id == (await get_department(db, parent)).id)
    return await _paginate(db, stmt, page, page_size)


async def department_tree(db: AsyncSession, organization: int | None) -> list[dict[str, Any]]:
    return build_tree(await _tree_rows(db, Department, organization), code="department_code", name="department_name")


async def department_children(db: AsyncSession, node: Department) -> list[Department]:
    return list((await db.scalars(select(Department).where(Department.parent_id == node.id)
                                  .order_by(Department.position, Department.id))).all())


async def department_subtree(db: AsyncSession, node: Department) -> list[Department]:
    return await _subtree(db, Department, node)


async def create_department(db: AsyncSession, body: Any, *, actor: Any) -> Department:
    organization_id = await require_organization(db)
    await _ensure_code_free(db, Department, Department.department_code, organization_id, body.department_code,
                            extra=(Department.deleted_at.is_(None),), label="Department code")
    parent = await _resolve_parent(db, Department, Department.department_code, body.parent, organization_id,
                                   "department")
    if body.head_of_department_user_id:
        await _existing_user(db, body.head_of_department_user_id)
    row = Department(
        **body.model_dump(exclude={"parent"}), organization_id=organization_id,
        parent_id=parent.id if parent else None, is_root=parent is None,
    )
    db.add(row)
    await db.flush()
    await _recompute(db, Department, "department", row.tenant_id, organization_id)
    await record_activity(db, action="department_created", actor_id=actor.id, subject_type="Department",
                          subject_id=row.id, changes={"after": {"code": row.department_code,
                                                                "parent": parent.department_code if parent else None}})
    return row


async def update_department(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> Department:
    row = await get_department(db, ref)
    _check_version(row, body.row_version, f"Department '{row.department_code}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "department_code" in changes and changes["department_code"].lower() != row.department_code.lower():
        await _ensure_code_free(db, Department, Department.department_code, row.organization_id,
                                changes["department_code"], except_id=row.id,
                                extra=(Department.deleted_at.is_(None),), label="Department code")
    if changes.get("head_of_department_user_id"):
        await _existing_user(db, changes["head_of_department_user_id"])
    await _apply(db, row, changes, action="department_updated", subject="Department", actor=actor)
    if {"department_code", "position"} & changes.keys():
        await _recompute(db, Department, "department", row.tenant_id, row.organization_id)
    if "status" in changes:
        await engine.bump_epoch(row.tenant_id)
    return row


async def move_department(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> Department:
    row = await get_department(db, ref)
    _check_version(row, body.row_version, f"Department '{row.department_code}'")
    parent = await _resolve_parent(db, Department, Department.department_code, body.parent, row.organization_id,
                                   "department")
    _refuse_cycle(row, parent, "department")
    if (parent.id if parent else None) == row.parent_id:
        return row
    before = row.parent_id
    row.parent_id = parent.id if parent else None
    row.is_root = parent is None
    await db.flush()
    await _recompute(db, Department, "department", row.tenant_id, row.organization_id)
    await record_activity(db, action="department_moved", actor_id=actor.id, subject_type="Department",
                          subject_id=row.id, changes={"before": {"parent_id": before},
                                                      "after": {"parent_id": row.parent_id}})
    return row


async def delete_department(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> Department:
    from app.modules.hr.model import EmploymentRecord
    from app.modules.rbac.model import UserRole

    row = await get_department(db, ref)
    blockers = {
        "child department(s)": select(func.count()).select_from(Department).where(Department.parent_id == row.id),
        "team(s)": select(func.count()).select_from(Team).where(Team.department_id == row.id),
        "job title(s)": select(func.count()).select_from(JobTitle).where(JobTitle.department_id == row.id),
        "employment record(s)": select(func.count()).select_from(EmploymentRecord)
        .where(EmploymentRecord.department_id == row.id),
        "role assignment(s)": select(func.count()).select_from(UserRole)
        .where(UserRole.department_id == row.id, UserRole.status == "active"),
    }
    for label, stmt in blockers.items():
        count = await db.scalar(stmt)
        if count:
            raise TeamsRuleError(f"Department '{row.department_code}' still has {count} {label}; move or remove them first")
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await _recompute(db, Department, "department", row.tenant_id, row.organization_id)
    await record_activity(db, action="department_deleted", actor_id=actor.id, subject_type="Department",
                          subject_id=row.id, context={"reason": reason})
    return row


# ── job titles ──────────────────────────────────────────────────────────────

async def get_job_title(db: AsyncSession, ref: str | int) -> JobTitle:
    return await _get(db, JobTitle, ref, JobTitle.job_code, "Job title")


async def list_job_titles(
    db: AsyncSession, *, q: str | None, status: str | None, department: str | None, organization: int | None,
    page: int, page_size: int,
) -> tuple[list[JobTitle], int]:
    stmt = select(JobTitle).order_by(JobTitle.organization_id, JobTitle.band_level.desc(), JobTitle.title)
    if organization is not None:
        stmt = stmt.where(JobTitle.organization_id == organization)
    if status:
        stmt = stmt.where(JobTitle.status == status)
    if q:
        stmt = stmt.where(JobTitle.title.ilike(f"%{q.strip()}%") | JobTitle.job_code.ilike(f"%{q.strip()}%"))
    if department is not None:
        stmt = stmt.where(JobTitle.department_id == (await get_department(db, department)).id)
    return await _paginate(db, stmt, page, page_size)


async def _department_of_org(db: AsyncSession, ref: str, organization_id: int) -> Department:
    dept = await get_department(db, ref)
    if dept.organization_id != organization_id:
        raise TeamsRuleError("The department belongs to a different organization",
                             data={"department_organization_id": dept.organization_id})
    return dept


async def create_job_title(db: AsyncSession, body: Any, *, actor: Any) -> JobTitle:
    organization_id = await require_organization(db)
    await _ensure_code_free(db, JobTitle, JobTitle.job_code, organization_id, body.job_code,
                            extra=(JobTitle.deleted_at.is_(None),), label="Job code")
    dept = await _department_of_org(db, body.department, organization_id) if body.department else None
    row = JobTitle(**body.model_dump(exclude={"department"}), organization_id=organization_id,
                   department_id=dept.id if dept else None)
    db.add(row)
    await db.flush()
    await record_activity(db, action="job_title_created", actor_id=actor.id, subject_type="JobTitle",
                          subject_id=row.id, changes={"after": {"code": row.job_code, "title": row.title}})
    return row


async def update_job_title(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> JobTitle:
    row = await get_job_title(db, ref)
    _check_version(row, body.row_version, f"Job title '{row.job_code}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "department"})
    if "job_code" in changes and changes["job_code"].lower() != row.job_code.lower():
        await _ensure_code_free(db, JobTitle, JobTitle.job_code, row.organization_id, changes["job_code"],
                                except_id=row.id, extra=(JobTitle.deleted_at.is_(None),), label="Job code")
    if "department" in body.model_fields_set:
        changes["department_id"] = (
            (await _department_of_org(db, body.department, row.organization_id)).id if body.department else None
        )
    await _apply(db, row, changes, action="job_title_updated", subject="JobTitle", actor=actor)
    return row


async def delete_job_title(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> JobTitle:
    from app.modules.hr.model import EmploymentRecord

    row = await get_job_title(db, ref)
    in_use = await db.scalar(select(func.count()).select_from(EmploymentRecord)
                             .where(EmploymentRecord.job_title_id == row.id))
    if in_use:
        raise TeamsRuleError(f"Job title '{row.job_code}' is held by {in_use} employment record(s)")
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await record_activity(db, action="job_title_deleted", actor_id=actor.id, subject_type="JobTitle",
                          subject_id=row.id, context={"reason": reason})
    return row


# ── team types ──────────────────────────────────────────────────────────────

async def get_team_type(db: AsyncSession, ref: str | int) -> TeamType:
    return await _get(db, TeamType, ref, TeamType.type_code, "Team type")


async def list_team_types(
    db: AsyncSession, *, q: str | None, status: str | None, organization: int | None, page: int, page_size: int,
) -> tuple[list[TeamType], int]:
    stmt = select(TeamType).order_by(TeamType.organization_id, TeamType.lft, TeamType.id)
    if organization is not None:
        stmt = stmt.where(TeamType.organization_id == organization)
    if status:
        stmt = stmt.where(TeamType.status == status)
    if q:
        stmt = stmt.where(TeamType.type_name.ilike(f"%{q.strip()}%") | TeamType.type_code.ilike(f"%{q.strip()}%"))
    return await _paginate(db, stmt, page, page_size)


async def team_type_tree(db: AsyncSession, organization: int | None) -> list[dict[str, Any]]:
    return build_tree(await _tree_rows(db, TeamType, organization), code="type_code", name="type_name")


async def create_team_type(db: AsyncSession, body: Any, *, actor: Any) -> TeamType:
    organization_id = await require_organization(db)
    await _ensure_code_free(db, TeamType, TeamType.type_code, organization_id, body.type_code,
                            extra=(TeamType.deleted_at.is_(None),), label="Team type code")
    parent = await _resolve_parent(db, TeamType, TeamType.type_code, body.parent, organization_id, "team type")
    row = TeamType(**body.model_dump(exclude={"parent"}), organization_id=organization_id,
                   parent_id=parent.id if parent else None, is_root=parent is None)
    db.add(row)
    await db.flush()
    await _recompute(db, TeamType, "team_type", row.tenant_id, organization_id)
    await record_activity(db, action="team_type_created", actor_id=actor.id, subject_type="TeamType",
                          subject_id=row.id, changes={"after": {"code": row.type_code}})
    return row


async def update_team_type(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> TeamType:
    row = await get_team_type(db, ref)
    _check_version(row, body.row_version, f"Team type '{row.type_code}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "type_code" in changes and changes["type_code"].lower() != row.type_code.lower():
        await _ensure_code_free(db, TeamType, TeamType.type_code, row.organization_id, changes["type_code"],
                                except_id=row.id, extra=(TeamType.deleted_at.is_(None),), label="Team type code")
    await _apply(db, row, changes, action="team_type_updated", subject="TeamType", actor=actor)
    if {"type_code", "position"} & changes.keys():
        await _recompute(db, TeamType, "team_type", row.tenant_id, row.organization_id)
    return row


async def move_team_type(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> TeamType:
    row = await get_team_type(db, ref)
    _check_version(row, body.row_version, f"Team type '{row.type_code}'")
    parent = await _resolve_parent(db, TeamType, TeamType.type_code, body.parent, row.organization_id, "team type")
    _refuse_cycle(row, parent, "team type")
    if (parent.id if parent else None) == row.parent_id:
        return row
    row.parent_id = parent.id if parent else None
    row.is_root = parent is None
    await db.flush()
    await _recompute(db, TeamType, "team_type", row.tenant_id, row.organization_id)
    await record_activity(db, action="team_type_moved", actor_id=actor.id, subject_type="TeamType", subject_id=row.id)
    return row


async def delete_team_type(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> TeamType:
    row = await get_team_type(db, ref)
    for label, stmt in {
        "child type(s)": select(func.count()).select_from(TeamType).where(TeamType.parent_id == row.id),
        "team(s)": select(func.count()).select_from(Team).where(Team.team_type_id == row.id),
        "team role(s)": select(func.count()).select_from(TeamRole).where(TeamRole.team_type_id == row.id),
    }.items():
        count = await db.scalar(stmt)
        if count:
            raise TeamsRuleError(f"Team type '{row.type_code}' still has {count} {label}")
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await _recompute(db, TeamType, "team_type", row.tenant_id, row.organization_id)
    await record_activity(db, action="team_type_deleted", actor_id=actor.id, subject_type="TeamType",
                          subject_id=row.id, context={"reason": reason})
    return row


# ── team roles ──────────────────────────────────────────────────────────────

async def get_team_role(db: AsyncSession, ref: str | int) -> TeamRole:
    return await _get(db, TeamRole, ref, TeamRole.role_code, "Team role")


async def list_team_roles(
    db: AsyncSession, *, q: str | None, status: str | None, team_type: str | None, organization: int | None,
    page: int, page_size: int,
) -> tuple[list[TeamRole], int]:
    stmt = select(TeamRole).order_by(TeamRole.organization_id, TeamRole.position, TeamRole.role_name)
    if organization is not None:
        stmt = stmt.where(TeamRole.organization_id == organization)
    if status:
        stmt = stmt.where(TeamRole.status == status)
    if q:
        stmt = stmt.where(TeamRole.role_name.ilike(f"%{q.strip()}%") | TeamRole.role_code.ilike(f"%{q.strip()}%"))
    if team_type is not None:
        stmt = stmt.where(TeamRole.team_type_id == (await get_team_type(db, team_type)).id)
    return await _paginate(db, stmt, page, page_size)


async def _resolve_rbac_role(
    db: AsyncSession, ref: str, organization_id: int, *, actor_grants: Grants | None,
) -> Any:
    """The RBAC role a team role maps to: usable in the team role's organization, and never a privilege escalation."""
    from app.modules.organizations.model import Organization
    from app.modules.rbac import service as rbac
    from app.modules.roles import service as roles_service

    role = await roles_service.get_role(db, ref)
    if role.status != "active" or not role.is_assignable:
        raise TeamsRuleError(f"Role '{role.code}' cannot be mapped (inactive, deprecated or not assignable)")
    owner_path = await db.scalar(select(Organization.hierarchy_path).where(Organization.id == role.organization_id))
    org_path = await db.scalar(select(Organization.hierarchy_path).where(Organization.id == organization_id))
    if not owner_path or not org_path or not org_path.startswith(owner_path):
        raise TeamsRuleError(f"Role '{role.code}' is not usable in this organization (it is owned elsewhere)")
    if actor_grants is not None:
        codes = set((await rbac.role_codes(db, [role]))[role.id])
        await rbac._check_can_grant(db, actor_grants, role, codes, Target(organization_id=organization_id))  # noqa: SLF001
    return role


async def _clear_other_defaults(db: AsyncSession, organization_id: int, team_type_id: int | None, except_id: int | None) -> None:
    stmt = select(TeamRole).where(TeamRole.organization_id == organization_id, TeamRole.is_default.is_(True))
    stmt = stmt.where(TeamRole.team_type_id == team_type_id if team_type_id is not None
                      else TeamRole.team_type_id.is_(None))
    if except_id is not None:
        stmt = stmt.where(TeamRole.id != except_id)
    for other in (await db.scalars(stmt)).all():
        other.is_default = False
    await db.flush()


async def create_team_role(db: AsyncSession, body: Any, *, actor: Any, grants: Grants) -> TeamRole:
    organization_id = await require_organization(db)
    await _ensure_code_free(
        db, TeamRole, TeamRole.role_code, organization_id, body.role_code,
        extra=(TeamRole.deleted_at.is_(None),
               (TeamRole.team_type_id == (await get_team_type(db, body.team_type)).id) if body.team_type
               else TeamRole.team_type_id.is_(None)),
        label="Team role code",
    )
    team_type = await get_team_type(db, body.team_type) if body.team_type else None
    if team_type and team_type.organization_id != organization_id:
        raise TeamsRuleError("The team type belongs to a different organization")
    rbac_role = await _resolve_rbac_role(db, body.rbac_role, organization_id, actor_grants=grants) if body.rbac_role else None
    if body.is_default:
        await _clear_other_defaults(db, organization_id, team_type.id if team_type else None, None)
    row = TeamRole(
        **body.model_dump(exclude={"team_type", "rbac_role"}), organization_id=organization_id,
        team_type_id=team_type.id if team_type else None, rbac_role_id=rbac_role.id if rbac_role else None,
    )
    db.add(row)
    await db.flush()
    await record_activity(db, action="team_role_created", actor_id=actor.id, subject_type="TeamRole",
                          subject_id=row.id, changes={"after": {"code": row.role_code,
                                                                "rbac_role": rbac_role.code if rbac_role else None}})
    if rbac_role:
        await engine.bump_epoch(row.tenant_id)
    return row


async def update_team_role(db: AsyncSession, ref: str, body: Any, *, actor: Any, grants: Grants) -> TeamRole:
    row = await get_team_role(db, ref)
    _check_version(row, body.row_version, f"Team role '{row.role_code}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "rbac_role"})
    if "role_code" in changes and changes["role_code"].lower() != row.role_code.lower():
        await _ensure_code_free(
            db, TeamRole, TeamRole.role_code, row.organization_id, changes["role_code"], except_id=row.id,
            extra=(TeamRole.deleted_at.is_(None),
                   (TeamRole.team_type_id == row.team_type_id) if row.team_type_id is not None
                   else TeamRole.team_type_id.is_(None)),
            label="Team role code",
        )
    if "rbac_role" in body.model_fields_set:
        changes["rbac_role_id"] = (
            (await _resolve_rbac_role(db, body.rbac_role, row.organization_id, actor_grants=grants)).id
            if body.rbac_role else None
        )
    if changes.get("is_default"):
        await _clear_other_defaults(db, row.organization_id, row.team_type_id, row.id)
    await _apply(db, row, changes, action="team_role_updated", subject="TeamRole", actor=actor)
    if {"rbac_role_id", "status", "is_assignable"} & changes.keys():
        await engine.bump_epoch(row.tenant_id)
    return row


async def delete_team_role(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> TeamRole:
    row = await get_team_role(db, ref)
    in_use = await db.scalar(select(func.count()).select_from(UserTeam).where(
        UserTeam.team_role_id == row.id, UserTeam.valid_until.is_(None)))
    if in_use:
        raise TeamsRuleError(f"Team role '{row.role_code}' is held by {in_use} current member(s)")
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await record_activity(db, action="team_role_deleted", actor_id=actor.id, subject_type="TeamRole",
                          subject_id=row.id, context={"reason": reason})
    await engine.bump_epoch(row.tenant_id)
    return row


# ── teams ───────────────────────────────────────────────────────────────────

async def get_team(db: AsyncSession, ref: str | int) -> Team:
    return await _get(db, Team, ref, Team.team_code, "Team")


async def list_teams(
    db: AsyncSession, *, q: str | None, status: str | None, team_type: str | None, department: str | None,
    organization: int | None, parent: str | None, page: int, page_size: int,
) -> tuple[list[Team], int]:
    stmt = select(Team).order_by(Team.organization_id, Team.lft, Team.id)
    if organization is not None:
        stmt = stmt.where(Team.organization_id == organization)
    if status:
        stmt = stmt.where(Team.status == status)
    if q:
        stmt = stmt.where(Team.team_name.ilike(f"%{q.strip()}%") | Team.team_code.ilike(f"%{q.strip()}%"))
    if team_type is not None:
        stmt = stmt.where(Team.team_type_id == (await get_team_type(db, team_type)).id)
    if department is not None:
        stmt = stmt.where(Team.department_id == (await get_department(db, department)).id)
    if parent is not None:
        stmt = stmt.where(Team.parent_id == (await get_team(db, parent)).id)
    return await _paginate(db, stmt, page, page_size)


async def team_tree(db: AsyncSession, organization: int | None) -> list[dict[str, Any]]:
    return build_tree(await _tree_rows(db, Team, organization), code="team_code", name="team_name")


async def team_children(db: AsyncSession, node: Team) -> list[Team]:
    return list((await db.scalars(select(Team).where(Team.parent_id == node.id)
                                  .order_by(Team.position, Team.id))).all())


async def team_subtree(db: AsyncSession, node: Team) -> list[Team]:
    return await _subtree(db, Team, node)


async def create_team(db: AsyncSession, body: Any, *, actor: Any) -> Team:
    organization_id = await require_organization(db)
    await _ensure_code_free(db, Team, Team.team_code, organization_id, body.team_code,
                            extra=(Team.deleted_at.is_(None),), label="Team code")
    team_type = await get_team_type(db, body.team_type)
    if team_type.organization_id != organization_id:
        raise TeamsRuleError("The team type belongs to a different organization")
    parent = await _resolve_parent(db, Team, Team.team_code, body.parent, organization_id, "team")
    dept = await _department_of_org(db, body.department, organization_id) if body.department else None
    if body.team_lead_user_id:
        await _existing_user(db, body.team_lead_user_id)
    row = Team(
        **body.model_dump(exclude={"team_type", "parent", "department"}), organization_id=organization_id,
        team_type_id=team_type.id, parent_id=parent.id if parent else None, is_root=parent is None,
        department_id=dept.id if dept else None,
    )
    db.add(row)
    await db.flush()
    await _recompute(db, Team, "team", row.tenant_id, organization_id)
    await record_activity(db, action="team_created", actor_id=actor.id, subject_type="Team", subject_id=row.id,
                          changes={"after": {"code": row.team_code, "type": team_type.type_code,
                                             "parent": parent.team_code if parent else None}})
    return row


async def update_team(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> Team:
    row = await get_team(db, ref)
    _check_version(row, body.row_version, f"Team '{row.team_code}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "team_type", "department"})
    if "team_code" in changes and changes["team_code"].lower() != row.team_code.lower():
        await _ensure_code_free(db, Team, Team.team_code, row.organization_id, changes["team_code"],
                                except_id=row.id, extra=(Team.deleted_at.is_(None),), label="Team code")
    if "team_type" in body.model_fields_set and body.team_type:
        team_type = await get_team_type(db, body.team_type)
        if team_type.organization_id != row.organization_id:
            raise TeamsRuleError("The team type belongs to a different organization")
        changes["team_type_id"] = team_type.id
    if "department" in body.model_fields_set:
        changes["department_id"] = (
            (await _department_of_org(db, body.department, row.organization_id)).id if body.department else None
        )
    if changes.get("team_lead_user_id"):
        await _existing_user(db, changes["team_lead_user_id"])
    await _apply(db, row, changes, action="team_updated", subject="Team", actor=actor)
    if {"team_code", "position"} & changes.keys():
        await _recompute(db, Team, "team", row.tenant_id, row.organization_id)
    if {"status", "department_id"} & changes.keys():
        await engine.bump_epoch(row.tenant_id)
    return row


async def move_team(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> Team:
    row = await get_team(db, ref)
    _check_version(row, body.row_version, f"Team '{row.team_code}'")
    parent = await _resolve_parent(db, Team, Team.team_code, body.parent, row.organization_id, "team")
    _refuse_cycle(row, parent, "team")
    if (parent.id if parent else None) == row.parent_id:
        return row
    before = row.parent_id
    row.parent_id = parent.id if parent else None
    row.is_root = parent is None
    await db.flush()
    await _recompute(db, Team, "team", row.tenant_id, row.organization_id)
    await record_activity(db, action="team_moved", actor_id=actor.id, subject_type="Team", subject_id=row.id,
                          changes={"before": {"parent_id": before}, "after": {"parent_id": row.parent_id}})
    return row


async def delete_team(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> Team:
    from app.modules.rbac.model import UserRole

    row = await get_team(db, ref)
    for label, stmt in {
        "child team(s)": select(func.count()).select_from(Team).where(Team.parent_id == row.id),
        "current member(s)": select(func.count()).select_from(UserTeam).where(
            UserTeam.team_id == row.id, UserTeam.valid_until.is_(None)),
        "role assignment(s)": select(func.count()).select_from(UserRole).where(
            UserRole.team_id == row.id, UserRole.status == "active"),
    }.items():
        count = await db.scalar(stmt)
        if count:
            raise TeamsRuleError(f"Team '{row.team_code}' still has {count} {label}; move or remove them first")
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await _recompute(db, Team, "team", row.tenant_id, row.organization_id)
    await record_activity(db, action="team_deleted", actor_id=actor.id, subject_type="Team", subject_id=row.id,
                          context={"reason": reason})
    return row


# ── membership ──────────────────────────────────────────────────────────────

def team_target(team: Team) -> Target:
    return Target(organization_id=team.organization_id, department_id=team.department_id, team_id=team.id)


async def get_member(db: AsyncSession, member_ref: str | int, *, team: Team | None = None) -> UserTeam:
    text_ref = str(member_ref)
    try:
        cond = UserTeam.uuid == uuid_lib.UUID(text_ref)
    except ValueError:
        if not text_ref.isdigit():
            raise NotFoundError(f"Membership '{member_ref}' not found") from None
        cond = UserTeam.id == int(text_ref)
    stmt = select(UserTeam).where(cond)
    if team is not None:
        stmt = stmt.where(UserTeam.team_id == team.id)
    row = await db.scalar(stmt.limit(1))
    if row is None:
        raise NotFoundError(f"Membership '{member_ref}' not found")
    return row


async def list_members(
    db: AsyncSession, team: Team, *, include_ended: bool, approval_status: str | None, page: int, page_size: int,
) -> tuple[list[UserTeam], int]:
    stmt = select(UserTeam).where(UserTeam.team_id == team.id).order_by(UserTeam.created_at.desc(), UserTeam.id)
    if not include_ended:
        stmt = stmt.where(UserTeam.valid_until.is_(None))
    if approval_status:
        stmt = stmt.where(UserTeam.approval_status == approval_status)
    return await _paginate(db, stmt, page, page_size)


async def my_memberships(db: AsyncSession, user_id: int, *, include_ended: bool = False) -> list[tuple[UserTeam, Team]]:
    stmt = (select(UserTeam, Team).join(Team, Team.id == UserTeam.team_id)
            .where(UserTeam.user_id == user_id).order_by(UserTeam.is_primary.desc(), Team.team_name))
    if not include_ended:
        stmt = stmt.where(UserTeam.valid_until.is_(None))
    return [(m, t) for m, t in (await db.execute(stmt)).all()]


async def _member_role(db: AsyncSession, team: Team, ref: str | None, *, grants: Grants) -> TeamRole | None:
    if ref:
        role = await get_team_role(db, ref)
    else:
        role = await db.scalar(select(TeamRole).where(
            TeamRole.organization_id == team.organization_id, TeamRole.is_default.is_(True),
            TeamRole.team_type_id == team.team_type_id, TeamRole.status == "active").limit(1))
        if role is None:
            role = await db.scalar(select(TeamRole).where(
                TeamRole.organization_id == team.organization_id, TeamRole.is_default.is_(True),
                TeamRole.team_type_id.is_(None), TeamRole.status == "active").limit(1))
    if role is None:
        return None
    if role.organization_id != team.organization_id:
        raise TeamsRuleError("The team role belongs to a different organization than the team")
    if role.team_type_id is not None and role.team_type_id != team.team_type_id:
        raise TeamsRuleError(f"Team role '{role.role_code}' is for a different team type")
    if role.status != "active" or not role.is_assignable:
        raise TeamsRuleError(f"Team role '{role.role_code}' cannot be assigned (inactive or not assignable)")
    if role.rbac_role_id:
        # Joining a role that carries RBAC permissions hands them out: same guard as any grant.
        from app.modules.rbac import service as rbac
        from app.modules.roles.model import Role

        rbac_role = await db.scalar(select(Role).where(Role.id == role.rbac_role_id))
        if rbac_role is not None:
            codes = set((await rbac.role_codes(db, [rbac_role]))[rbac_role.id])
            await rbac._check_can_grant(db, grants, rbac_role, codes, team_target(team))  # noqa: SLF001
    return role


async def _clear_primary(db: AsyncSession, user_id: int, except_id: int | None) -> None:
    stmt = update(UserTeam).where(
        UserTeam.user_id == user_id, UserTeam.is_primary.is_(True), UserTeam.valid_until.is_(None),
    ).values(is_primary=False, row_version=UserTeam.row_version + 1)
    if except_id is not None:
        stmt = stmt.where(UserTeam.id != except_id)
    await db.execute(stmt.execution_options(synchronize_session="fetch"))


async def add_member(db: AsyncSession, team: Team, body: Any, *, actor: Any, grants: Grants) -> UserTeam:
    if team.status != TeamStatus.ACTIVE.value:
        raise TeamsRuleError(f"Team '{team.team_code}' is {team.status}; only active teams take members")
    user = await _existing_user(db, body.user_id)
    role = await _member_role(db, team, body.team_role, grants=grants)
    # Approved on the spot only when the actor may approve here AND is not approving themselves.
    can_approve = await grants.allows(db, "teams.membership:approve", team_target(team)) and actor.id != user.id
    row = UserTeam(
        user_id=user.id, team_id=team.id, team_role_id=role.id if role else None, is_primary=body.is_primary,
        notes=body.notes, valid_until=body.valid_until, organization_id=team.organization_id,
        approval_status=(ApprovalStatus.APPROVED if can_approve else ApprovalStatus.PENDING).value,
        approved_by=actor.id if can_approve else None,
        approved_at=dt.datetime.now(dt.UTC) if can_approve else None,
    )
    if body.valid_from:
        row.valid_from = body.valid_from
    if body.is_primary:
        await _clear_primary(db, user.id, None)
    user_id, team_code, tenant_id = user.id, team.team_code, user.tenant_id   # a failed flush expires instances
    try:
        # Added INSIDE the savepoint (see rbac.service.assign_role): begin_nested autoflushes pending rows first.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"User {user_id} already has an open membership of '{team_code}' with this role",
            data={"user_id": user_id, "team": team_code},
        ) from exc
    await record_activity(
        db, action="team_member_added", actor_id=actor.id, subject_type="Team", subject_id=team.id,
        changes={"after": {"user_id": user.id, "team_role": role.role_code if role else None,
                           "approval": row.approval_status}},
    )
    await engine.forget_user(tenant_id, user_id)
    return row


async def add_members_bulk(
    db: AsyncSession, items: list[Any], *, actor: Any, grants: Grants, partial: bool,
) -> tuple[list[UserTeam], list[int], list[dict[str, Any]]]:
    """Bulk add across teams. Every item is authorized against ITS team (docs/rbac-module.md §4.10).

    ``partial=False`` (default) is all-or-nothing: one denied item refuses the whole batch and nothing is
    written. ``partial=True`` adds what is permitted and reports the denied indexes and per-item errors.
    """
    if len(items) > BULK_LIMIT:
        raise TeamsRuleError(f"At most {BULK_LIMIT} items per request", data={"limit": BULK_LIMIT})
    teams = [await get_team(db, item.team) for item in items]
    targets = [team_target(t) for t in teams]
    if partial:
        decisions = await grants.allows_many(db, "teams.membership:assign", targets)
    else:
        await grants.require_all(db, "teams.membership:assign", targets)
        decisions = [True] * len(items)
    added: list[UserTeam] = []
    denied = [i for i, ok in enumerate(decisions) if not ok]
    errors: list[dict[str, Any]] = []
    for i, (item, team, ok) in enumerate(zip(items, teams, decisions, strict=True)):
        if not ok:
            continue
        try:
            async with db.begin_nested():
                added.append(await add_member(db, team, item, actor=actor, grants=grants))
        except (ConflictError, TeamsRuleError, NotFoundError, ForbiddenError) as exc:
            if not partial:
                raise
            errors.append({"index": i, "code": exc.code, "msg": exc.msg})
    return added, denied, errors


async def update_member(db: AsyncSession, team: Team, member_ref: str, body: Any, *, actor: Any, grants: Grants) -> UserTeam:
    row = await get_member(db, member_ref, team=team)
    _check_version(row, body.row_version, "Membership")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "team_role"})
    if "team_role" in body.model_fields_set:
        role = await _member_role(db, team, body.team_role, grants=grants) if body.team_role else None
        changes["team_role_id"] = role.id if role else None
    if changes.get("is_primary"):
        await _clear_primary(db, row.user_id, row.id)
    if changes.get("valid_until") and changes["valid_until"] <= row.valid_from:
        raise TeamsRuleError("valid_until must be after valid_from")
    try:
        async with db.begin_nested():
            await _apply(db, row, changes, action="team_member_updated", subject="UserTeam", actor=actor)
    except IntegrityError as exc:
        raise ConflictError("That change collides with another open membership of this user") from exc
    await engine.forget_user(row.tenant_id, row.user_id)
    return row


async def remove_member(db: AsyncSession, team: Team, member_ref: str, *, reason: str, actor: Any) -> UserTeam:
    """Leave the team: close the window (history) — or drop a membership that never started."""
    row = await get_member(db, member_ref, team=team)
    now = dt.datetime.now(dt.UTC)
    if row.valid_until is not None and row.valid_until <= now:
        raise TeamsRuleError("This membership has already ended")
    if row.valid_from >= now:
        row.soft_delete(reason=reason, by=actor.id)
    else:
        row.valid_until = now
        row.status = MembershipStatus.INACTIVE.value
    row.is_primary = False
    await db.flush()
    await record_activity(db, action="team_member_removed", actor_id=actor.id, subject_type="Team",
                          subject_id=team.id, changes={"before": {"user_id": row.user_id}},
                          context={"reason": reason})
    await engine.forget_user(row.tenant_id, row.user_id)
    return row


async def decide_member(
    db: AsyncSession, team: Team, member_ref: str, *, approve: bool, notes: str | None, actor: Any,
) -> UserTeam:
    """Approve or reject a pending membership. Nobody decides their own."""
    row = await get_member(db, member_ref, team=team)
    if row.approval_status != ApprovalStatus.PENDING.value:
        raise TeamsRuleError(f"This membership is already {row.approval_status}")
    if row.user_id == actor.id:
        raise ForbiddenError("You cannot approve or reject your own membership")
    now = dt.datetime.now(dt.UTC)
    row.approval_status = (ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED).value
    row.approved_by, row.approved_at, row.approval_notes = actor.id, now, notes
    if not approve:
        row.status = MembershipStatus.INACTIVE.value
        row.is_primary = False
        if row.valid_from < now:
            row.valid_until = now
    await db.flush()
    await record_activity(db, action="team_member_approved" if approve else "team_member_rejected",
                          actor_id=actor.id, subject_type="Team", subject_id=team.id,
                          changes={"after": {"user_id": row.user_id}}, context={"notes": notes})
    await engine.forget_user(row.tenant_id, row.user_id)
    return row
