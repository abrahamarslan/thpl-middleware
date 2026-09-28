"""The evaluator — who may do what, where (docs/rbac-module.md §4).

A user's effective permissions are the UNION of their **grants**:

    base role     ``users.role_id``                     scope: home organization + descendants
    assignment    ``rbac.user_roles`` (active, in window)   scope: the row's own
    team role     approved, in-window ``user_teams``    scope: that team (+ child teams)

Each grant is (role, scope). A role's permissions are its ``role_permissions`` rows
(``explicit``) or computed from the catalogue (``all`` / ``all_but_owner_only``),
with ``manage`` expanded to create/read/update/delete. Deny-by-default; additive only.

Evaluation is against a :class:`Target` — the organization (default: the request's
bound one), and optionally the department / team the action concerns:

    tenant        matches everything in the tenant
    organization  the target org is the scope org, or (descendants) sits under it
    department    the target's department is in the scope's expanded id set
    team          the target's team is in the scope's expanded id set

Department/team scopes are expanded to id sets WHEN GRANTS ARE LOADED, so matching is
a set lookup and a tree change just bumps the epoch — no bounds are cached.

Caching — Redis only, deliberately no in-process layer (each worker would go stale
independently after a revoke). One key per user holding ``{epoch, grants}``; the
tenant-wide epoch is bumped on structural change and invalidates every user at once.
The TTL is clipped to the next grant start/expiry so a time-boxed grant is never
honoured late (or ignored late) and no expiry job is needed. A cache failure falls
open to the database — it must never become a 500.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ForbiddenError
from app.core.conf import settings
from app.database.tenancy import current_organization_id
from app.modules.rbac.catalogue import ALL_CODES, OWNER_ONLY, expand
from app.modules.rbac.enums import GrantMode, ScopeType
from app.modules.rbac.model import Permission, RolePermission, UserRole
from app.modules.rbac.platform import is_platform_admin
from app.modules.roles.model import Role

logger = structlog.get_logger("app.rbac")

_GRANTS_KEY = "rbac:grants:{tenant}:{user}"
_EPOCH_KEY = "rbac:epoch:{tenant}"


# ── value objects ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Target:
    """What an action concerns. ``None`` fields mean "not specified"."""

    organization_id: int | None = None
    department_id: int | None = None
    team_id: int | None = None
    #: True = the action concerns the TENANT itself (e.g. creating a new ROOT organization), not any
    #: organization in it — only a tenant-scoped grant covers it.
    tenant_level: bool = False


@dataclass(frozen=True, slots=True)
class Grant:
    source: str                       # base | assignment | team
    scope: str                        # tenant | organization | department | team
    role_id: int
    role_code: str
    level: int
    mode: str
    permissions: frozenset[str] = frozenset()      # explicit codes, already expanded
    org_id: int | None = None
    org_path: str | None = None
    descendants: bool = False
    node_ids: frozenset[int] = frozenset()         # department/team subtree, expanded at load

    def has(self, code: str) -> bool:
        if self.mode == GrantMode.ALL.value:
            return code in ALL_CODES
        if self.mode == GrantMode.ALL_BUT_OWNER_ONLY.value:
            return code in ALL_CODES and code not in OWNER_ONLY
        return code in self.permissions

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["permissions"] = sorted(self.permissions)
        data["node_ids"] = sorted(self.node_ids)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Grant:
        return cls(**{**data, "permissions": frozenset(data["permissions"]),
                      "node_ids": frozenset(data["node_ids"])})


@dataclass(slots=True)
class Grants:
    """A user's loaded grants, with the evaluation logic. One per request."""

    user_id: int
    tenant_id: int | None
    home_org_id: int | None
    grants: list[Grant]
    platform_admin: bool = False
    _paths: dict[int, str | None] = field(default_factory=dict)

    # ── evaluation ──────────────────────────────────────────────────────────
    def _target_org(self, target: Target | None) -> int | None:
        if target is not None and target.organization_id is not None:
            return target.organization_id
        return current_organization_id() or self.home_org_id

    async def _path_of(self, db: AsyncSession, org_id: int | None) -> str | None:
        if org_id is None:
            return None
        if org_id not in self._paths:
            from app.modules.organizations.model import Organization

            self._paths[org_id] = await db.scalar(
                select(Organization.hierarchy_path).where(Organization.id == org_id)
            )
        return self._paths[org_id]

    async def _covers(self, db: AsyncSession, grant: Grant, org_id: int | None, target: Target | None) -> bool:
        if grant.scope == ScopeType.TENANT.value:
            return True
        if target is not None and target.tenant_level:
            return False                      # only a tenant-wide grant may act on the tenant itself
        if grant.scope == ScopeType.ORGANIZATION.value:
            if org_id is None or grant.org_id is None:
                return False
            if org_id == grant.org_id:
                return True
            if grant.descendants and grant.org_path:
                path = await self._path_of(db, org_id)
                return bool(path) and path.startswith(grant.org_path)
            return False
        if grant.scope == ScopeType.DEPARTMENT.value:
            return target is not None and target.department_id in grant.node_ids
        if grant.scope == ScopeType.TEAM.value:
            return target is not None and target.team_id in grant.node_ids
        return False

    async def allows(self, db: AsyncSession, code: str, target: Target | None = None) -> bool:
        if self.platform_admin:
            return True
        org_id = self._target_org(target)
        for grant in self.grants:
            if grant.has(code) and await self._covers(db, grant, org_id, target):
                return True
        return False

    async def allows_many(self, db: AsyncSession, code: str, targets: list[Target | None]) -> list[bool]:
        """Per-item decisions for a bulk operation (docs/rbac-module.md §4.10)."""
        return [await self.allows(db, code, t) for t in targets]

    async def require(self, db: AsyncSession, code: str, target: Target | list[Target] | tuple[Target, ...] | None = None) -> None:
        """Refuse unless ``code`` is held at the target — or at EVERY target when several are given
        (an action that touches two places, e.g. moving an organization under another parent)."""
        targets = list(target) if isinstance(target, (list, tuple)) else [target]
        for one in targets:
            if not await self.allows(db, code, one):
                raise ForbiddenError(
                    f"Missing permission '{code}'",
                    data={"permission": code, "organization_id": self._target_org(one),
                          "tenant_level": bool(one and one.tenant_level)},
                )

    async def require_all(self, db: AsyncSession, code: str, targets: list[Target | None]) -> None:
        """All-or-nothing bulk authorization: any denied item refuses the whole batch."""
        decisions = await self.allows_many(db, code, targets)
        denied = [i for i, ok in enumerate(decisions) if not ok]
        if denied:
            raise ForbiddenError(
                f"Missing permission '{code}' for {len(denied)} of {len(decisions)} item(s)",
                data={"permission": code, "denied_indexes": denied},
            )

    # ── introspection (UI, shape decisions — NOT a gate) ────────────────────
    def can_anywhere(self, code: str) -> bool:
        """Held at SOME scope. For choosing a response's shape or a UI affordance, never to authorize."""
        return self.platform_admin or any(g.has(code) for g in self.grants)

    @property
    def max_level(self) -> int:
        return max((g.level for g in self.grants), default=0)

    def summary(self) -> dict[str, Any]:
        return {
            "platform_admin": self.platform_admin,
            "grants": [
                {
                    "source": g.source, "scope": g.scope, "role": g.role_code, "role_id": g.role_id,
                    "organization_id": g.org_id, "include_descendants": g.descendants,
                    "permissions": sorted(ALL_CODES if g.mode == GrantMode.ALL.value else
                                          ALL_CODES - OWNER_ONLY if g.mode == GrantMode.ALL_BUT_OWNER_ONLY.value
                                          else g.permissions),
                }
                for g in self.grants
            ],
        }


# ── cache ───────────────────────────────────────────────────────────────────

def _ttl_seconds(boundaries: list[dt.datetime], now: dt.datetime) -> int:
    ttl = int(settings.RBAC_CACHE_TTL_SECONDS)
    if ttl <= 0:
        return 0
    future = [(b - now).total_seconds() for b in boundaries if b > now]
    if future:
        ttl = min(ttl, max(1, int(min(future))))
    return ttl


async def _cache_read(tenant_id: int, user_id: int) -> list[Grant] | None:
    if int(settings.RBAC_CACHE_TTL_SECONDS) <= 0:
        return None
    try:
        from app.database.redis import redis_client

        epoch, raw = await redis_client.mget(
            _EPOCH_KEY.format(tenant=tenant_id), _GRANTS_KEY.format(tenant=tenant_id, user=user_id),
        )
        if raw is None:
            return None
        payload = json.loads(raw)
        if str(payload.get("epoch")) != str(epoch or 0):
            return None
        return [Grant.from_json(g) for g in payload["grants"]]
    except Exception as exc:  # noqa: BLE001 — a cache must never cause a 500
        logger.warning("rbac_cache_read_failed", error=str(exc))
        return None


async def _cache_write(tenant_id: int, user_id: int, grants: list[Grant], ttl: int) -> None:
    if ttl <= 0:
        return
    try:
        from app.database.redis import redis_client

        epoch = await redis_client.get(_EPOCH_KEY.format(tenant=tenant_id))
        payload = json.dumps({"epoch": str(epoch or 0), "grants": [g.to_json() for g in grants]})
        await redis_client.set(_GRANTS_KEY.format(tenant=tenant_id, user=user_id), payload, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rbac_cache_write_failed", error=str(exc))


async def bump_epoch(tenant_id: int | None) -> None:
    """Invalidate every user's cached grants in a tenant (role/permission/tree/org change)."""
    if tenant_id is None:
        return
    try:
        from app.database.redis import redis_client

        await redis_client.incr(_EPOCH_KEY.format(tenant=tenant_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("rbac_epoch_bump_failed", error=str(exc))


async def forget_user(tenant_id: int | None, user_id: int) -> None:
    """Drop one user's cached grants (assignment / membership / base-role change)."""
    if tenant_id is None:
        return
    try:
        from app.database.redis import redis_client

        await redis_client.delete(_GRANTS_KEY.format(tenant=tenant_id, user=user_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("rbac_forget_failed", error=str(exc))


# ── loading ─────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class _Raw:
    source: str
    role_id: int
    scope: str
    org_id: int | None
    descendants: bool
    department_id: int | None = None
    team_id: int | None = None


def _in_window(start: dt.datetime | None, end: dt.datetime | None, now: dt.datetime,
               boundaries: list[dt.datetime]) -> bool:
    """Apply a validity window; record the next boundary so the cache TTL can be clipped."""
    if start is not None and start > now:
        boundaries.append(start)
        return False
    if end is not None:
        if end <= now:
            return False
        boundaries.append(end)
    return True


async def _explicit_permissions(db: AsyncSession, role_ids: list[int]) -> dict[int, frozenset[str]]:
    if not role_ids:
        return {}
    rows = await db.execute(
        select(RolePermission.role_id, Permission.permission_code)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id.in_(role_ids), Permission.deprecated_at.is_(None))
    )
    out: dict[int, set[str]] = {}
    for role_id, code in rows.all():
        out.setdefault(role_id, set()).add(code)
    return {rid: frozenset(expand(codes)) for rid, codes in out.items()}


async def load_from_db(db: AsyncSession, user: Any, now: dt.datetime | None = None) -> tuple[list[Grant], list[dt.datetime]]:
    """Build a user's grants from the database. Returns the grants and the future validity boundaries."""
    now = now or dt.datetime.now(dt.UTC)
    boundaries: list[dt.datetime] = []
    raws: list[_Raw] = []

    if getattr(user, "role_id", None) and getattr(user, "organization_id", None):
        raws.append(_Raw("base", user.role_id, ScopeType.ORGANIZATION.value, user.organization_id, True))

    assignments = (await db.scalars(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.status == "active")
    )).all()
    for a in assignments:
        if _in_window(a.valid_from, a.valid_to, now, boundaries):
            raws.append(_Raw("assignment", a.role_id, a.scope_type, a.organization_id,
                             a.include_descendants, a.department_id, a.team_id))

    from app.modules.teams import grants as team_grants   # the one sanctioned rbac → teams edge

    for m in await team_grants.membership_grants(db, user.id):
        if _in_window(m.valid_from, m.valid_until, now, boundaries):
            raws.append(_Raw("team", m.role_id, ScopeType.TEAM.value, m.organization_id, True, None, m.team_id))

    if not raws:
        return [], boundaries

    role_ids = sorted({r.role_id for r in raws})
    roles = {role.id: role for role in (await db.scalars(select(Role).where(Role.id.in_(role_ids)))).all()
             if role.status == "active"}
    explicit = await _explicit_permissions(
        db, [rid for rid, role in roles.items() if role.grant_mode == GrantMode.EXPLICIT.value],
    )

    org_ids = {r.org_id for r in raws if r.scope == ScopeType.ORGANIZATION.value and r.org_id}
    paths: dict[int, str] = {}
    if org_ids:
        from app.modules.organizations.model import Organization

        paths = dict((await db.execute(
            select(Organization.id, Organization.hierarchy_path).where(Organization.id.in_(org_ids))
        )).all())

    grants: list[Grant] = []
    for r in raws:
        role = roles.get(r.role_id)
        if role is None:
            continue
        node_ids: frozenset[int] = frozenset()
        if r.scope == ScopeType.DEPARTMENT.value and r.department_id:
            node_ids = await team_grants.subtree_ids(db, "department", r.department_id, descendants=r.descendants)
        elif r.scope == ScopeType.TEAM.value and r.team_id:
            node_ids = await team_grants.subtree_ids(db, "team", r.team_id, descendants=r.descendants)
        grants.append(Grant(
            source=r.source, scope=r.scope, role_id=role.id, role_code=role.code,
            level=role.hierarchy_level, mode=role.grant_mode,
            permissions=explicit.get(role.id, frozenset()),
            org_id=r.org_id, org_path=paths.get(r.org_id) if r.org_id else None,
            descendants=r.descendants, node_ids=node_ids,
        ))
    return grants, boundaries


async def load_grants(db: AsyncSession, user: Any) -> Grants:
    """A user's grants — from the cache when fresh, else the database (and cached)."""
    tenant_id = getattr(user, "tenant_id", None)
    common = dict(
        user_id=user.id, tenant_id=tenant_id, home_org_id=getattr(user, "organization_id", None),
        platform_admin=is_platform_admin(user),
    )
    if tenant_id is not None:
        cached = await _cache_read(tenant_id, user.id)
        if cached is not None:
            return Grants(grants=cached, **common)
    now = dt.datetime.now(dt.UTC)
    grants, boundaries = await load_from_db(db, user, now)
    if tenant_id is not None:
        await _cache_write(tenant_id, user.id, grants, _ttl_seconds(boundaries, now))
    return Grants(grants=grants, **common)


__all__ = [
    "Grant", "Grants", "Target", "bump_epoch", "forget_user", "load_from_db", "load_grants",
]
