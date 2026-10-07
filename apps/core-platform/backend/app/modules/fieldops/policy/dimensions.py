"""Scope dimensions — which layer targets apply to a person right now (plan §4.4).

A dimension is a registry entry: its precedence ``rank``, the table that proves a ``scope_id`` exists
(write-time validation, same tenant), and an async provider returning the ids that apply in a
:class:`PolicyContext`. The resolver never names a dimension; adding one (``beat`` when the beats
module lands, a district, a vehicle class …) is: the target table exists → ``shifts.<x>_id`` carries
the assignment → one ``Dimension`` entry here. ``Scope.BEAT`` is in the vocabulary (and the CHECK)
from day one; its provider returns nothing until beats exist, and a write naming a beat is refused
(``scope_not_available``) rather than stored to never apply.

Work context comes from the SHIFT (its frozen hub/beat), never from live GPS: re-resolving config as a
phone crosses a polygon would oscillate at the boundary and make "which rules applied" unanswerable.
Without a shift, the hub is the user's assigned hub for the business day (``hubs.user_hub_assignments``,
falling back to the employment record) — it may be NULL, and then no hub layer applies.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.policy.settings import Scope


@dataclass(slots=True)
class PolicyContext:
    """Who, when, and (optionally) the work they are doing."""

    tenant_id: int
    organization_id: int
    user_id: int
    role_id: int | None
    at: dt.datetime
    shift_hub_id: int | None = None
    shift_beat_id: int | None = None
    has_shift: bool = False
    #: Resolve without work context (login): hub/team-free, see ``Binding.LOGIN``.
    identity_only: bool = False
    #: Memoized per resolution.
    cache: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_user(cls, user: Any, *, at: dt.datetime | None = None, shift: Any = None,
                 identity_only: bool = False) -> PolicyContext:
        return cls(tenant_id=user.tenant_id, organization_id=shift.organization_id if shift is not None
                   else user.organization_id, user_id=user.id, role_id=user.role_id,
                   at=at or dt.datetime.now(dt.UTC), shift_hub_id=getattr(shift, "hub_id", None),
                   shift_beat_id=getattr(shift, "beat_id", None), has_shift=shift is not None,
                   identity_only=identity_only)


async def org_ancestry(db: AsyncSession, ctx: PolicyContext) -> dict[int, int]:
    """{organization id: depth} for the context's organization and every ancestor (root first)."""
    if "ancestry" not in ctx.cache:
        rows = (await db.execute(text("""
            SELECT o.id, o.depth FROM org_management.organizations o
              JOIN org_management.organizations home ON home.id = :org AND home.tenant_id = :tenant
             WHERE o.tenant_id = :tenant AND home.hierarchy_path LIKE o.hierarchy_path || '%'
        """), {"org": ctx.organization_id, "tenant": ctx.tenant_id})).all()
        ctx.cache["ancestry"] = {int(r.id): int(r.depth or 0) for r in rows} or {ctx.organization_id: 0}
    return ctx.cache["ancestry"]


async def _organizations(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    return tuple(await org_ancestry(db, ctx))


async def _roles(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    # The BASE role only: a contextual grant changes what someone may do, never what they must do.
    return (ctx.role_id,) if ctx.role_id else ()


async def _teams(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    rows = (await db.execute(text("""
        SELECT DISTINCT team_id FROM teams.user_teams
         WHERE tenant_id = :tenant AND user_id = :user AND deleted_at IS NULL
           AND status = 'active' AND approval_status = 'approved'
           AND (valid_until IS NULL OR valid_until > :at)
    """), {"tenant": ctx.tenant_id, "user": ctx.user_id, "at": ctx.at})).scalars().all()
    return tuple(sorted(int(r) for r in rows))


async def _hubs(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    if ctx.has_shift:
        return (ctx.shift_hub_id,) if ctx.shift_hub_id else ()
    from app.modules.fieldops.service.common import org_timezone
    from app.modules.fieldops.clock import business_date
    from app.modules.hubs.assignments import hub_for

    day = business_date(ctx.at, await org_timezone(db, ctx.organization_id))
    hub_id = await hub_for(db, tenant_id=ctx.tenant_id, user_id=ctx.user_id, day=day)
    return (hub_id,) if hub_id else ()


async def _beats(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    return (ctx.shift_beat_id,) if ctx.shift_beat_id else ()


async def _users(db: AsyncSession, ctx: PolicyContext) -> tuple[int, ...]:
    return (ctx.user_id,)


@dataclass(frozen=True, slots=True)
class Dimension:
    scope: Scope
    rank: int
    #: ``schema.table`` proving a scope_id (``None`` for organization; ``""`` = not available yet).
    table: str | None
    provider: Callable[[AsyncSession, PolicyContext], Awaitable[tuple[int, ...]]]
    #: Ignored when resolving without work context (login).
    needs_work_context: bool = False

    @property
    def available(self) -> bool:
        return self.table != ""


DIMENSIONS: dict[Scope, Dimension] = {d.scope: d for d in (
    Dimension(Scope.ORGANIZATION, 0, None, _organizations),
    Dimension(Scope.ROLE, 10, "public.roles", _roles),
    Dimension(Scope.TEAM, 20, "teams.teams", _teams, needs_work_context=True),
    Dimension(Scope.HUB, 30, "public.hubs", _hubs, needs_work_context=True),
    Dimension(Scope.BEAT, 40, "", _beats, needs_work_context=True),       # beats module not built yet
    Dimension(Scope.USER, 50, "public.users", _users),
)}


async def applicable_ids(db: AsyncSession, ctx: PolicyContext) -> dict[Scope, tuple[int, ...]]:
    out: dict[Scope, tuple[int, ...]] = {}
    for scope, dim in DIMENSIONS.items():
        if ctx.identity_only and dim.needs_work_context:
            out[scope] = ()
            continue
        out[scope] = await dim.provider(db, ctx)
    return out


async def scope_target_exists(db: AsyncSession, scope: Scope, scope_id: int, tenant_id: int) -> bool:
    dim = DIMENSIONS[scope]
    if not dim.table:
        return False
    schema, table = dim.table.split(".")
    return bool(await db.scalar(text(
        f'SELECT EXISTS (SELECT 1 FROM "{schema}"."{table}" WHERE id = :id AND tenant_id = :t AND deleted_at IS NULL)'
    ), {"id": scope_id, "t": tenant_id}))


__all__ = ["DIMENSIONS", "Dimension", "PolicyContext", "applicable_ids", "org_ancestry", "scope_target_exists"]
