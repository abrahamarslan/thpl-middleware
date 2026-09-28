"""What the RBAC engine needs from ``teams`` — and nothing else.

Team membership is a source of grants, and department/team scopes have to be
expanded to the ids of their subtree. Both need the teams tables, so the queries
live HERE (teams owns its schema) and ``rbac.engine`` imports this module lazily:
the one sanctioned rbac → teams edge (docs/rbac-module.md §3.2).

Nothing in this module imports ``rbac``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.enums import ApprovalStatus, MembershipStatus, TeamStatus
from app.modules.teams.model import Department, Team, TeamRole, UserTeam


@dataclass(frozen=True, slots=True)
class MembershipGrant:
    """A team membership that maps to an RBAC role (``team_roles.rbac_role_id``)."""

    role_id: int
    team_id: int
    organization_id: int
    valid_from: dt.datetime
    valid_until: dt.datetime | None


async def membership_grants(db: AsyncSession, user_id: int) -> list[MembershipGrant]:
    """Approved, active memberships whose team role carries an RBAC role.

    The time window is NOT applied here (the engine applies it to every grant source the
    same way and uses the boundaries to clip the cache lifetime).
    """
    rows = await db.execute(
        select(TeamRole.rbac_role_id, UserTeam.team_id, Team.organization_id,
               UserTeam.valid_from, UserTeam.valid_until)
        .join(Team, Team.id == UserTeam.team_id)
        .join(TeamRole, TeamRole.id == UserTeam.team_role_id)
        .where(
            UserTeam.user_id == user_id,
            UserTeam.status == MembershipStatus.ACTIVE.value,
            UserTeam.approval_status == ApprovalStatus.APPROVED.value,
            TeamRole.rbac_role_id.is_not(None),
            Team.status == TeamStatus.ACTIVE.value,
        )
    )
    return [MembershipGrant(*row) for row in rows.all()]


async def subtree_ids(db: AsyncSession, kind: str, node_id: int, *, descendants: bool) -> frozenset[int]:
    """Ids of a department/team and (optionally) everything under it, by nested-set bounds."""
    model = Department if kind == "department" else Team
    node = await db.scalar(select(model).where(model.id == node_id))
    if node is None:
        return frozenset()
    if not descendants:
        return frozenset({node.id})
    ids = (await db.scalars(
        select(model.id).where(
            model.organization_id == node.organization_id,
            model.lft >= node.lft, model.rgt <= node.rgt,
        )
    )).all()
    return frozenset(ids) | {node.id}
