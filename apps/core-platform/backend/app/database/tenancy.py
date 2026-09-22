"""Tenancy runtime — who is acting, for which tenant/organization, enforced
on every query and every write (docs/tenancy/README.md §4).

The context
-----------
Three context variables (async-safe: each request / task has its own):

    tenant_id        the tenant every query is scoped to (None = system scope)
    organization_id  the organization new rows belong to (None = tenant-wide)
    actor            Actor(user_id, name) stamped into created_by/_name, updated_by/_name

Set by:
  * the API — ``bind_user(user)`` in ``get_current_user`` (every authenticated request);
  * background work — ``tenant_scope(...)`` (Zoho sync runs, CLI, tasks);
  * nothing — system scope: no read filter; new rows go to the DEFAULT tenant
    (``DEFAULT_TENANT_CODE``). This keeps single-tenant deployments, seeders
    and migrations working without ceremony.

What is enforced (session events, registered on import from db.py)
------------------------------------------------------------------
READ   every ORM SELECT / UPDATE / DELETE touching a tenant-bound model gets
       ``tenant_id = :current`` (like the soft-delete filter). Escape hatch
       for platform code: ``.execution_options(all_tenants=True)``.
INSERT tenant_id ← context (or the default tenant); organization_id ←
       context when unset (or DEFAULT_ORGANIZATION_CODE within the default
       tenant); created_by / created_by_name ← actor;
       app_version ← settings.VERSION.
UPDATE updated_by / updated_by_name ← actor (only when a user is acting);
       app_version ← settings.VERSION.
GUARD  inserting or modifying a row of ANOTHER tenant while a tenant context
       is active raises ``TenancyError`` — before any SQL is sent.

The database adds the second wall: composite FK (tenant_id, organization_id)
→ organizations(tenant_id, id), so a row can never point at another tenant's
organization even through raw SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import event, text
from sqlalchemy.orm import Session, with_loader_criteria

logger = structlog.get_logger("app.tenancy")


class TenancyError(RuntimeError):
    """A write crossed a tenant boundary, or no tenant could be resolved."""


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: int | None
    name: str

    @property
    def is_system(self) -> bool:
        return self.user_id is None


SYSTEM = Actor(None, "system")

_tenant: ContextVar[int | None] = ContextVar("tenant_id", default=None)
_organization: ContextVar[int | None] = ContextVar("organization_id", default=None)
_actor: ContextVar[Actor] = ContextVar("actor", default=SYSTEM)


def current_tenant_id() -> int | None:
    return _tenant.get()


def current_organization_id() -> int | None:
    return _organization.get()


def current_actor() -> Actor:
    return _actor.get()


@contextmanager
def tenant_scope(
    tenant_id: int | None,
    organization_id: int | None = None,
    actor: Actor | None = None,
) -> Iterator[None]:
    """Run a block as a tenant (and optionally an organization / actor)."""
    tokens = (_tenant.set(tenant_id), _organization.set(organization_id), _actor.set(actor or current_actor()))
    structlog.contextvars.bind_contextvars(tenant_id=tenant_id, organization_id=organization_id)
    try:
        yield
    finally:
        _actor.reset(tokens[2])
        _organization.reset(tokens[1])
        _tenant.reset(tokens[0])
        structlog.contextvars.bind_contextvars(tenant_id=_tenant.get(), organization_id=_organization.get())


def bind_user(user: Any, *, organization_id: int | None = None) -> None:
    """Request scope from the authenticated user (the request task owns it)."""
    name = (getattr(user, "name", None) or getattr(user, "email", None) or f"user:{user.id}")
    _tenant.set(getattr(user, "tenant_id", None))
    _organization.set(organization_id if organization_id is not None else getattr(user, "organization_id", None))
    _actor.set(Actor(getattr(user, "id", None), str(name)[:255]))
    structlog.contextvars.bind_contextvars(
        tenant_id=_tenant.get(), organization_id=_organization.get(), user_id=getattr(user, "id", None),
    )


def system_actor(component: str) -> Actor:
    """Actor for background writers: ``created_by_name = 'system:<component>'``."""
    return Actor(None, f"system:{component}")


# ── default tenant + organization ───────────────────────────────────────────

_default_cache: dict[str, int] = {}
_default_org_cache: dict[tuple[int, str], int | None] = {}


def _default_code() -> str:
    from app.core.conf import settings

    return settings.DEFAULT_TENANT_CODE


def _default_org_code() -> str:
    from app.core.conf import settings

    return settings.DEFAULT_ORGANIZATION_CODE


def default_tenant_id_sync(session: Session) -> int:
    """The default tenant's id (cached per process). Sync: usable in flush events."""
    code = _default_code()
    if code in _default_cache:
        return _default_cache[code]
    tenant_id = session.execute(
        text("SELECT id FROM org_management.tenants WHERE tenant_code = :code AND deleted_at IS NULL"),
        {"code": code},
    ).scalar()
    if tenant_id is None:
        raise TenancyError(
            f"no tenant context and the default tenant '{code}' does not exist "
            "(run `alembic upgrade head`, or set DEFAULT_TENANT_CODE)"
        )
    _default_cache[code] = int(tenant_id)
    return _default_cache[code]


def default_organization_id_sync(session: Session, tenant_id: int) -> int | None:
    """The default organization's id for a tenant (cached per process).

    ``DEFAULT_ORGANIZATION_CODE`` empty = disabled (returns None: rows stay
    tenant-wide). Unlike the default tenant, a missing organization is not an
    error — it simply means the deployment has no single-organization default.
    """
    code = _default_org_code()
    if not code:
        return None
    key = (tenant_id, code)
    if key in _default_org_cache:
        return _default_org_cache[key]
    org_id = session.execute(
        text("SELECT id FROM org_management.organizations "
             "WHERE tenant_id = :tenant AND org_code = :code AND deleted_at IS NULL"),
        {"tenant": tenant_id, "code": code},
    ).scalar()
    _default_org_cache[key] = int(org_id) if org_id is not None else None
    return _default_org_cache[key]


async def resolve_tenant_id(db, code: str | None = None) -> int:
    """Async lookup by tenant code (default tenant when ``code`` is empty).
    Raw SQL: the database layer never imports a feature module."""
    code = code or _default_code()
    tenant_id = await db.scalar(
        text("SELECT id FROM org_management.tenants WHERE tenant_code = :code AND deleted_at IS NULL"),
        {"code": code},
    )
    if tenant_id is None:
        raise TenancyError(f"tenant '{code}' does not exist")
    return int(tenant_id)


async def write_tenant_id(db) -> int:
    """Tenant for a Core-level INSERT (bypasses the flush stamping): the
    context's tenant, else the default tenant."""
    tenant_id = _tenant.get()
    if tenant_id is not None:
        return tenant_id
    return await db.run_sync(default_tenant_id_sync)


def clear_default_cache() -> None:
    _default_cache.clear()
    _default_org_cache.clear()


# ── session events ──────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def _columns(cls: type) -> frozenset[str]:
    table = getattr(cls, "__table__", None)
    return frozenset(table.c.keys()) if table is not None else frozenset()


def _tenant_bound():
    from app.database.mixins import TenantBound

    return TenantBound


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(execute_state) -> None:
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    if execute_state.is_column_load or execute_state.is_relationship_load:
        return
    if execute_state.execution_options.get("all_tenants", False):
        return
    tenant_id = _tenant.get()
    if tenant_id is None:
        return                                                   # system scope
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(_tenant_bound(), lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
    )


@event.listens_for(Session, "before_flush")
def _stamp_rows(session: Session, _flush_context, _instances) -> None:
    from app.core.conf import settings

    tenant_id, organization_id, actor = _tenant.get(), _organization.get(), _actor.get()
    bound = _tenant_bound()

    for obj in session.new:
        cols = _columns(type(obj))
        if isinstance(obj, bound):
            if obj.tenant_id is None:
                obj.tenant_id = tenant_id if tenant_id is not None else default_tenant_id_sync(session)
            elif tenant_id is not None and obj.tenant_id != tenant_id:
                raise TenancyError(
                    f"cannot create {type(obj).__name__} in tenant {obj.tenant_id} "
                    f"from tenant {tenant_id}"
                )
            if "organization_id" in cols and getattr(obj, "organization_id", None) is None \
                    and type(obj).__name__ != "Organization":
                if organization_id is not None:
                    obj.organization_id = organization_id
                elif _default_org_code() and obj.tenant_id == default_tenant_id_sync(session):
                    # Only the DEFAULT tenant gets the default organization; an
                    # explicit other-tenant context is never re-scoped.
                    obj.organization_id = default_organization_id_sync(session, obj.tenant_id)
        if "created_by_name" in cols and getattr(obj, "created_by_name", None) is None:
            obj.created_by_name = actor.name
            if getattr(obj, "created_by", None) is None:
                obj.created_by = actor.user_id
        if "app_version" in cols:
            obj.app_version = settings.VERSION

    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        cols = _columns(type(obj))
        if isinstance(obj, bound) and tenant_id is not None and obj.tenant_id != tenant_id:
            raise TenancyError(
                f"cannot modify {type(obj).__name__} of tenant {obj.tenant_id} from tenant {tenant_id}"
            )
        if "updated_by" in cols and actor.user_id is not None:
            obj.updated_by = actor.user_id
            if "updated_by_name" in cols:
                obj.updated_by_name = actor.name
        if "app_version" in cols:
            obj.app_version = settings.VERSION


__all__ = [
    "SYSTEM",
    "Actor",
    "TenancyError",
    "bind_user",
    "clear_default_cache",
    "current_actor",
    "current_organization_id",
    "current_tenant_id",
    "default_organization_id_sync",
    "default_tenant_id_sync",
    "resolve_tenant_id",
    "system_actor",
    "tenant_scope",
    "write_tenant_id",
]
