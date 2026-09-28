"""Whose field data a manager may READ — the interim data scope for location data.

RBAC decides WHETHER a caller may read shifts/visits/tracks (``Perm``); it does not yet
filter WHICH rows (docs/rbac-module.md: data scope is not built — reads are tenant-wide).
For field operations that is not acceptable: a team manager must not browse every rep's
tracks in the tenant. Until RBAC grows data scope, this module derives the visible set from
the SAME grants the guard used:

* a tenant-scoped grant of the permission            → everyone in the tenant;
* an organization-scoped grant                       → everyone in that organization (and its
                                                        subtree when the grant covers descendants);
* a team / department-scoped grant                   → the members of those teams, and of the
                                                        teams under those departments;
* always, in addition                                → the caller's direct reports
                                                        (``hr.employment_records.reporting_manager_user_id``)
                                                        and the caller themself.

This is the first consumer RBAC data scope should replace (improvement-document D8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, false, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.engine import Grants
from app.modules.rbac.enums import ScopeType


@dataclass(slots=True)
class Visible:
    unrestricted: bool = False
    org_ids: set[int] = field(default_factory=set)
    org_paths: list[str] = field(default_factory=list)
    user_ids: set[int] = field(default_factory=set)

    def filter(self, user_col, org_col) -> ColumnElement[bool] | None:
        """A WHERE clause for a table with a user and an organization column (None = no filter)."""
        if self.unrestricted:
            return None
        conditions: list[ColumnElement[bool]] = []
        if self.org_ids:
            conditions.append(org_col.in_(self.org_ids))
        if self.user_ids:
            conditions.append(user_col.in_(self.user_ids))
        return or_(*conditions) if conditions else false()

    def allows_user(self, user_id: int, organization_id: int | None) -> bool:
        return self.unrestricted or user_id in self.user_ids or (organization_id in self.org_ids)


async def visible(db: AsyncSession, grants: Grants, code: str, *, actor_id: int) -> Visible:
    if grants.platform_admin:
        return Visible(unrestricted=True)
    out = Visible(user_ids={actor_id})
    team_ids: set[int] = set()
    department_ids: set[int] = set()
    for grant in grants.grants:
        if not grant.has(code):
            continue
        if grant.scope == ScopeType.TENANT.value:
            return Visible(unrestricted=True)
        if grant.scope == ScopeType.ORGANIZATION.value and grant.org_id is not None:
            out.org_ids.add(grant.org_id)
            if grant.descendants and grant.org_path:
                out.org_paths.append(grant.org_path)
        elif grant.scope == ScopeType.TEAM.value:
            team_ids |= set(grant.node_ids)
        elif grant.scope == ScopeType.DEPARTMENT.value:
            department_ids |= set(grant.node_ids)

    if out.org_paths:
        rows = (await db.execute(text(
            "SELECT id FROM org_management.organizations WHERE deleted_at IS NULL AND "
            + " OR ".join(f"hierarchy_path LIKE :p{i}" for i in range(len(out.org_paths)))
        ), {f"p{i}": f"{path}%" for i, path in enumerate(out.org_paths)})).scalars().all()
        out.org_ids |= set(rows)

    if department_ids:
        rows = (await db.execute(text(
            "SELECT id FROM teams.teams WHERE deleted_at IS NULL AND department_id = ANY(:d)"
        ), {"d": list(department_ids)})).scalars().all()
        team_ids |= set(rows)
    if team_ids:
        rows = (await db.execute(text(
            "SELECT DISTINCT user_id FROM teams.user_teams WHERE team_id = ANY(:t) AND deleted_at IS NULL "
            "AND status = 'active' AND approval_status = 'approved' AND (valid_until IS NULL OR valid_until > now())"
        ), {"t": list(team_ids)})).scalars().all()
        out.user_ids |= set(rows)

    reports = (await db.execute(text(
        "SELECT user_id FROM employment_records WHERE reporting_manager_user_id = :me "
        "AND is_current AND deleted_at IS NULL"
    ), {"me": actor_id})).scalars().all()
    out.user_ids |= set(reports)
    return out


__all__ = ["Visible", "visible"]
