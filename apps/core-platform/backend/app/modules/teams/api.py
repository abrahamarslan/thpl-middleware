"""Teams HTTP API.

| Prefix | What | Permissions |
|---|---|---|
| ``/api/departments`` | departments (tree) | ``teams.department:*`` |
| ``/api/job-titles`` | job titles | ``teams.job_title:*`` |
| ``/api/team-types`` | team classification (tree) | ``teams.team_type:*`` |
| ``/api/team-roles`` | roles within a team (may map to an RBAC role) | ``teams.team_role:*`` |
| ``/api/teams`` | teams (tree) and their members | ``teams.team:*``, ``teams.membership:*`` |
| ``/api/me/teams`` | my memberships | any signed-in user |

``{ref}`` is a uuid (preferred), a numeric id, or a code (looked up in the request's organization).
Every route takes ONE kind of guard — ``Perm(code[, target=…])`` — see ``rbac.deps``. Lists are
tenant-wide by default (``?organization=`` narrows them); visibility scoping by team/department is
the documented, not-yet-implemented "data scope" phase (docs/rbac-module.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.rbac.deps import GrantsDep, Perm
from app.modules.teams import service
from app.modules.teams.deps import (
    department_target,
    job_title_target,
    team_ref_target,
    team_role_target,
    team_type_target,
)
from app.modules.teams.schema import (
    BulkResult,
    DepartmentCreate,
    DepartmentOut,
    DepartmentUpdate,
    JobTitleCreate,
    JobTitleOut,
    JobTitleUpdate,
    MemberAdd,
    MemberDecision,
    MemberOut,
    MembersBulk,
    MemberUpdate,
    Move,
    TeamCreate,
    TeamOut,
    TeamRoleCreate,
    TeamRoleOut,
    TeamRoleUpdate,
    TeamTypeCreate,
    TeamTypeOut,
    TeamTypeUpdate,
    TeamUpdate,
    TreeNode,
)
from app.modules.users.deps import CurrentUser

departments_router = APIRouter()
job_titles_router = APIRouter()
team_types_router = APIRouter()
team_roles_router = APIRouter()
teams_router = APIRouter()
me_teams_router = APIRouter()
_M = "teams"


async def _org_id(db, ref: str | None) -> int | None:
    if not ref:
        return None
    from app.modules.organizations import service as orgs

    return (await orgs.get_organization(db, ref)).id


def _page(items, total, page, page_size, out):
    return ResponseModel(data=PageModel(
        items=[out.model_validate(i) for i in items], page=page, page_size=page_size, total=total,
        has_more=page * page_size < total,
    ))


# ═══════════════════════════════ departments ═════════════════════════════════

@departments_router.get("", response_model=ResponseModel[PageModel[DepartmentOut]])
async def list_departments(
    _: Perm("teams.department:read"), db: DBSession,
    q: str | None = Query(None, max_length=100), status: str | None = Query(None, pattern="^(active|inactive|archived)$"),
    organization: str | None = Query(None, description="Organization uuid, code or id"),
    parent: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_departments(
        db, q=q, status=status, organization=await _org_id(db, organization), parent=parent,
        page=page, page_size=page_size)
    return _page(rows, total, page, page_size, DepartmentOut)


@departments_router.get("/tree", response_model=ResponseModel[list[TreeNode]])
async def department_tree(_: Perm("teams.department:read"), db: DBSession, organization: str | None = Query(None)):
    return ResponseModel.ok(data=await service.department_tree(db, await _org_id(db, organization)))


@departments_router.post("", response_model=ResponseModel[DepartmentOut], status_code=201)
async def create_department(actor: Perm("teams.department:create"), db: DBSession, body: DepartmentCreate):
    row = await service.create_department(db, body, actor=actor)
    return ResponseModel.ok(data=DepartmentOut.model_validate(row), module=_M, msg_key="department_created",
                            name=row.department_name)


@departments_router.get("/{ref}", response_model=ResponseModel[DepartmentOut])
async def get_department(_: Perm("teams.department:read", target=department_target), db: DBSession, ref: str):
    return ResponseModel.ok(data=DepartmentOut.model_validate(await service.get_department(db, ref)))


@departments_router.get("/{ref}/children", response_model=ResponseModel[list[DepartmentOut]])
async def department_children(_: Perm("teams.department:read", target=department_target), db: DBSession, ref: str):
    node = await service.get_department(db, ref)
    return ResponseModel.ok(data=[DepartmentOut.model_validate(r) for r in await service.department_children(db, node)])


@departments_router.get("/{ref}/subtree", response_model=ResponseModel[list[DepartmentOut]])
async def department_subtree(_: Perm("teams.department:read", target=department_target), db: DBSession, ref: str):
    node = await service.get_department(db, ref)
    return ResponseModel.ok(data=[DepartmentOut.model_validate(r) for r in await service.department_subtree(db, node)])


@departments_router.patch("/{ref}", response_model=ResponseModel[DepartmentOut])
async def update_department(
    actor: Perm("teams.department:update", target=department_target), db: DBSession, ref: str, body: DepartmentUpdate,
):
    row = await service.update_department(db, ref, body, actor=actor)
    return ResponseModel.ok(data=DepartmentOut.model_validate(row), module=_M, msg_key="department_updated",
                            name=row.department_name)


@departments_router.post("/{ref}/move", response_model=ResponseModel[DepartmentOut])
async def move_department(
    actor: Perm("teams.department:manage", target=department_target), db: DBSession, ref: str, body: Move,
):
    row = await service.move_department(db, ref, body, actor=actor)
    return ResponseModel.ok(data=DepartmentOut.model_validate(row), module=_M, msg_key="department_moved",
                            name=row.department_name)


@departments_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_department(
    actor: Perm("teams.department:delete", target=department_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    row = await service.delete_department(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="department_deleted", name=row.department_name)


# ═══════════════════════════════ job titles ══════════════════════════════════

@job_titles_router.get("", response_model=ResponseModel[PageModel[JobTitleOut]])
async def list_job_titles(
    _: Perm("teams.job_title:read"), db: DBSession, q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(active|inactive|deprecated)$"),
    department: str | None = Query(None), organization: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_job_titles(
        db, q=q, status=status, department=department, organization=await _org_id(db, organization),
        page=page, page_size=page_size)
    return _page(rows, total, page, page_size, JobTitleOut)


@job_titles_router.post("", response_model=ResponseModel[JobTitleOut], status_code=201)
async def create_job_title(actor: Perm("teams.job_title:create"), db: DBSession, body: JobTitleCreate):
    row = await service.create_job_title(db, body, actor=actor)
    return ResponseModel.ok(data=JobTitleOut.model_validate(row), module=_M, msg_key="job_title_created", name=row.title)


@job_titles_router.get("/{ref}", response_model=ResponseModel[JobTitleOut])
async def get_job_title(_: Perm("teams.job_title:read", target=job_title_target), db: DBSession, ref: str):
    return ResponseModel.ok(data=JobTitleOut.model_validate(await service.get_job_title(db, ref)))


@job_titles_router.patch("/{ref}", response_model=ResponseModel[JobTitleOut])
async def update_job_title(
    actor: Perm("teams.job_title:update", target=job_title_target), db: DBSession, ref: str, body: JobTitleUpdate,
):
    row = await service.update_job_title(db, ref, body, actor=actor)
    return ResponseModel.ok(data=JobTitleOut.model_validate(row), module=_M, msg_key="job_title_updated", name=row.title)


@job_titles_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_job_title(
    actor: Perm("teams.job_title:delete", target=job_title_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    row = await service.delete_job_title(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="job_title_deleted", name=row.title)


# ═══════════════════════════════ team types ══════════════════════════════════

@team_types_router.get("", response_model=ResponseModel[PageModel[TeamTypeOut]])
async def list_team_types(
    _: Perm("teams.team_type:read"), db: DBSession, q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(active|inactive|deprecated)$"),
    organization: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_team_types(
        db, q=q, status=status, organization=await _org_id(db, organization), page=page, page_size=page_size)
    return _page(rows, total, page, page_size, TeamTypeOut)


@team_types_router.get("/tree", response_model=ResponseModel[list[TreeNode]])
async def team_type_tree(_: Perm("teams.team_type:read"), db: DBSession, organization: str | None = Query(None)):
    return ResponseModel.ok(data=await service.team_type_tree(db, await _org_id(db, organization)))


@team_types_router.post("", response_model=ResponseModel[TeamTypeOut], status_code=201)
async def create_team_type(actor: Perm("teams.team_type:create"), db: DBSession, body: TeamTypeCreate):
    row = await service.create_team_type(db, body, actor=actor)
    return ResponseModel.ok(data=TeamTypeOut.model_validate(row), module=_M, msg_key="team_type_created",
                            name=row.type_name)


@team_types_router.get("/{ref}", response_model=ResponseModel[TeamTypeOut])
async def get_team_type(_: Perm("teams.team_type:read", target=team_type_target), db: DBSession, ref: str):
    return ResponseModel.ok(data=TeamTypeOut.model_validate(await service.get_team_type(db, ref)))


@team_types_router.patch("/{ref}", response_model=ResponseModel[TeamTypeOut])
async def update_team_type(
    actor: Perm("teams.team_type:update", target=team_type_target), db: DBSession, ref: str, body: TeamTypeUpdate,
):
    row = await service.update_team_type(db, ref, body, actor=actor)
    return ResponseModel.ok(data=TeamTypeOut.model_validate(row), module=_M, msg_key="team_type_updated",
                            name=row.type_name)


@team_types_router.post("/{ref}/move", response_model=ResponseModel[TeamTypeOut])
async def move_team_type(
    actor: Perm("teams.team_type:manage", target=team_type_target), db: DBSession, ref: str, body: Move,
):
    row = await service.move_team_type(db, ref, body, actor=actor)
    return ResponseModel.ok(data=TeamTypeOut.model_validate(row), module=_M, msg_key="team_type_moved",
                            name=row.type_name)


@team_types_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_team_type(
    actor: Perm("teams.team_type:delete", target=team_type_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    row = await service.delete_team_type(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="team_type_deleted", name=row.type_name)


# ═══════════════════════════════ team roles ══════════════════════════════════

@team_roles_router.get("", response_model=ResponseModel[PageModel[TeamRoleOut]])
async def list_team_roles(
    _: Perm("teams.team_role:read"), db: DBSession, q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(active|inactive|deprecated)$"),
    team_type: str | None = Query(None), organization: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_team_roles(
        db, q=q, status=status, team_type=team_type, organization=await _org_id(db, organization),
        page=page, page_size=page_size)
    return _page(rows, total, page, page_size, TeamRoleOut)


@team_roles_router.post("", response_model=ResponseModel[TeamRoleOut], status_code=201)
async def create_team_role(
    actor: Perm("teams.team_role:create"), grants: GrantsDep, db: DBSession, body: TeamRoleCreate,
):
    row = await service.create_team_role(db, body, actor=actor, grants=grants)
    return ResponseModel.ok(data=TeamRoleOut.model_validate(row), module=_M, msg_key="team_role_created",
                            name=row.role_name)


@team_roles_router.get("/{ref}", response_model=ResponseModel[TeamRoleOut])
async def get_team_role(_: Perm("teams.team_role:read", target=team_role_target), db: DBSession, ref: str):
    return ResponseModel.ok(data=TeamRoleOut.model_validate(await service.get_team_role(db, ref)))


@team_roles_router.patch("/{ref}", response_model=ResponseModel[TeamRoleOut])
async def update_team_role(
    actor: Perm("teams.team_role:update", target=team_role_target), grants: GrantsDep, db: DBSession,
    ref: str, body: TeamRoleUpdate,
):
    row = await service.update_team_role(db, ref, body, actor=actor, grants=grants)
    return ResponseModel.ok(data=TeamRoleOut.model_validate(row), module=_M, msg_key="team_role_updated",
                            name=row.role_name)


@team_roles_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_team_role(
    actor: Perm("teams.team_role:delete", target=team_role_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    row = await service.delete_team_role(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="team_role_deleted", name=row.role_name)


# ═══════════════════════════════ teams ═══════════════════════════════════════

@teams_router.get("", response_model=ResponseModel[PageModel[TeamOut]])
async def list_teams(
    _: Perm("teams.team:read"), db: DBSession, q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(active|inactive|archived|pending)$"),
    team_type: str | None = Query(None), department: str | None = Query(None), parent: str | None = Query(None),
    organization: str | None = Query(None), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_teams(
        db, q=q, status=status, team_type=team_type, department=department, parent=parent,
        organization=await _org_id(db, organization), page=page, page_size=page_size)
    return _page(rows, total, page, page_size, TeamOut)


@teams_router.get("/tree", response_model=ResponseModel[list[TreeNode]])
async def team_tree(_: Perm("teams.team:read"), db: DBSession, organization: str | None = Query(None)):
    return ResponseModel.ok(data=await service.team_tree(db, await _org_id(db, organization)))


@teams_router.post("", response_model=ResponseModel[TeamOut], status_code=201)
async def create_team(actor: Perm("teams.team:create"), db: DBSession, body: TeamCreate):
    row = await service.create_team(db, body, actor=actor)
    return ResponseModel.ok(data=TeamOut.model_validate(row), module=_M, msg_key="team_created", name=row.team_name)


@teams_router.post("/members/bulk", response_model=ResponseModel[BulkResult], status_code=201)
async def add_members_bulk(
    actor: Perm("teams.membership:assign"), grants: GrantsDep, db: DBSession, body: MembersBulk,
    partial: bool = Query(False, description="Add what is permitted and report the rest; default is all-or-nothing"),
):
    """Add members across teams. Every item is authorized against ITS team (all-or-nothing unless ``partial``)."""
    added, denied, errors = await service.add_members_bulk(
        db, body.items, actor=actor, grants=grants, partial=partial)
    return ResponseModel.ok(
        data=BulkResult(added=[MemberOut.model_validate(m) for m in added], denied=denied, errors=errors),
        module=_M, msg_key="members_added", count=len(added), name="teams",
    )


@teams_router.get("/{ref}", response_model=ResponseModel[TeamOut])
async def get_team(_: Perm("teams.team:read", target=team_ref_target), db: DBSession, ref: str):
    return ResponseModel.ok(data=TeamOut.model_validate(await service.get_team(db, ref)))


@teams_router.get("/{ref}/children", response_model=ResponseModel[list[TeamOut]])
async def team_children(_: Perm("teams.team:read", target=team_ref_target), db: DBSession, ref: str):
    node = await service.get_team(db, ref)
    return ResponseModel.ok(data=[TeamOut.model_validate(r) for r in await service.team_children(db, node)])


@teams_router.get("/{ref}/subtree", response_model=ResponseModel[list[TeamOut]])
async def team_subtree(_: Perm("teams.team:read", target=team_ref_target), db: DBSession, ref: str):
    node = await service.get_team(db, ref)
    return ResponseModel.ok(data=[TeamOut.model_validate(r) for r in await service.team_subtree(db, node)])


@teams_router.patch("/{ref}", response_model=ResponseModel[TeamOut])
async def update_team(
    actor: Perm("teams.team:update", target=team_ref_target), db: DBSession, ref: str, body: TeamUpdate,
):
    row = await service.update_team(db, ref, body, actor=actor)
    return ResponseModel.ok(data=TeamOut.model_validate(row), module=_M, msg_key="team_updated", name=row.team_name)


@teams_router.post("/{ref}/move", response_model=ResponseModel[TeamOut])
async def move_team(
    actor: Perm("teams.team:manage", target=team_ref_target), db: DBSession, ref: str, body: Move,
):
    row = await service.move_team(db, ref, body, actor=actor)
    return ResponseModel.ok(data=TeamOut.model_validate(row), module=_M, msg_key="team_moved", name=row.team_name)


@teams_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_team(
    actor: Perm("teams.team:delete", target=team_ref_target), db: DBSession, ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    row = await service.delete_team(db, ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=None, module=_M, msg_key="team_deleted", name=row.team_name)


# ── membership ──────────────────────────────────────────────────────────────

@teams_router.get("/{ref}/members", response_model=ResponseModel[PageModel[MemberOut]])
async def list_members(
    _: Perm("teams.membership:read", target=team_ref_target), db: DBSession, ref: str,
    include_ended: bool = Query(False), approval_status: str | None = Query(None, pattern="^(pending|approved|rejected|cancelled)$"),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    team = await service.get_team(db, ref)
    rows, total = await service.list_members(
        db, team, include_ended=include_ended, approval_status=approval_status, page=page, page_size=page_size)
    return _page(rows, total, page, page_size, MemberOut)


@teams_router.post("/{ref}/members", response_model=ResponseModel[MemberOut], status_code=201)
async def add_member(
    actor: Perm("teams.membership:assign", target=team_ref_target), grants: GrantsDep, db: DBSession,
    ref: str, body: MemberAdd,
):
    team = await service.get_team(db, ref)
    row = await service.add_member(db, team, body, actor=actor, grants=grants)
    return ResponseModel.ok(data=MemberOut.model_validate(row), module=_M, msg_key="member_added", name=team.team_name)


@teams_router.patch("/{ref}/members/{member_ref}", response_model=ResponseModel[MemberOut])
async def update_member(
    actor: Perm("teams.membership:assign", target=team_ref_target), grants: GrantsDep, db: DBSession,
    ref: str, member_ref: str, body: MemberUpdate,
):
    team = await service.get_team(db, ref)
    row = await service.update_member(db, team, member_ref, body, actor=actor, grants=grants)
    return ResponseModel.ok(data=MemberOut.model_validate(row), module=_M, msg_key="member_updated")


@teams_router.delete("/{ref}/members/{member_ref}", response_model=ResponseModel[MemberOut])
async def remove_member(
    actor: Perm("teams.membership:assign", target=team_ref_target), db: DBSession, ref: str, member_ref: str,
    reason: str = Query(..., min_length=3, max_length=500),
):
    team = await service.get_team(db, ref)
    row = await service.remove_member(db, team, member_ref, reason=reason, actor=actor)
    return ResponseModel.ok(data=MemberOut.model_validate(row), module=_M, msg_key="member_removed", name=team.team_name)


@teams_router.post("/{ref}/members/{member_ref}/approve", response_model=ResponseModel[MemberOut])
async def approve_member(
    actor: Perm("teams.membership:approve", target=team_ref_target), db: DBSession, ref: str, member_ref: str,
    body: MemberDecision | None = None,
):
    team = await service.get_team(db, ref)
    row = await service.decide_member(db, team, member_ref, approve=True, notes=body.notes if body else None,
                                      actor=actor)
    return ResponseModel.ok(data=MemberOut.model_validate(row), module=_M, msg_key="member_approved")


@teams_router.post("/{ref}/members/{member_ref}/reject", response_model=ResponseModel[MemberOut])
async def reject_member(
    actor: Perm("teams.membership:approve", target=team_ref_target), db: DBSession, ref: str, member_ref: str,
    body: MemberDecision | None = None,
):
    team = await service.get_team(db, ref)
    row = await service.decide_member(db, team, member_ref, approve=False, notes=body.notes if body else None,
                                      actor=actor)
    return ResponseModel.ok(data=MemberOut.model_validate(row), module=_M, msg_key="member_rejected")


# ═══════════════════════════════ me ══════════════════════════════════════════

class _MyMembership(MemberOut):
    team_code: str | None = None
    team_name: str | None = None


@me_teams_router.get("/teams", response_model=ResponseModel[list[_MyMembership]])
async def my_teams(user: CurrentUser, db: DBSession, include_ended: bool = Query(False)):
    """My team memberships (any signed-in user)."""
    out = []
    for membership, team in await service.my_memberships(db, user.id, include_ended=include_ended):
        item = _MyMembership.model_validate(membership)
        item.team_code, item.team_name = team.team_code, team.team_name
        out.append(item)
    return ResponseModel.ok(data=out)


__all__ = [
    "departments_router", "job_titles_router", "me_teams_router",
    "team_roles_router", "team_types_router", "teams_router",
]
