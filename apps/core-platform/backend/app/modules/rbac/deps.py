"""FastAPI guards — ONE way to protect a route.

    @router.post("")                                   # org-level: the request's organization
    async def create_team(user: Perm("teams.team:create"), ...): ...

    @router.patch("/{ref}")                            # resource-level: the target is loaded
    async def update_team(                             # DECLARATIVELY, by a dependency
        ref: str, user: Perm("teams.team:update", target=team_target), ...): ...

There is deliberately no imperative "call ``require`` inside the handler" paradigm for
authorizing a route: two styles invite the route that declares the org-level check and
forgets the resource-level one. ``target=`` is the whole resource-level story — it names
a dependency that loads the row from the path and returns a :class:`Target`, so the
department/team scoped grants are matched against the REAL resource before the handler
runs. ``tests/test_rbac_routes.py`` walks every route and fails if a mutating route has
no ``Perm`` (and is not on the explicit self-service/public allow-list), or if a
resource-scoped module's route with a path parameter has no ``target``.

The check itself is cheap: grants are loaded once per request (Redis, else the database)
and shared by every dependency through :data:`GrantsDep`.

Bulk endpoints authorize each item with ``grants.require_all(db, code, targets)``
(all-or-nothing) — see docs/rbac-module.md §4.10. That is a batch of the SAME declared
permission, not a second guard paradigm; the route still declares ``Perm(code)``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request

from app.database.db import DBSession
from app.modules.rbac import engine
from app.modules.rbac.catalogue import require_known
from app.modules.rbac.engine import Grants, Target
from app.modules.users.deps import CurrentUser
from app.modules.users.model import User

#: Attribute the guards carry so the route test can find them.
MARKER = "__rbac__"


async def get_grants(user: CurrentUser, db: DBSession) -> Grants:
    """The caller's grants, loaded once per request (FastAPI caches the dependency)."""
    return await engine.load_grants(db, user)


GrantsDep = Annotated[Grants, Depends(get_grants)]


async def _no_target() -> None:
    return None


def Perm(code: str, *, target: Callable[..., Any] | None = None):  # noqa: N802 — used like a type, like TenantAdmin
    """Require ``code``; returns an ``Annotated[User, Depends(...)]`` for the route parameter.

    ``target`` — a dependency returning a :class:`Target` for resource-level checks
    (department / team scoped grants). Omit it for org-level permissions.

    An unknown code raises AT IMPORT, so a typo is a startup failure rather than a
    permanent 403.
    """
    require_known(code)
    resolve_target = target or _no_target

    async def _guard(
        user: CurrentUser,
        grants: GrantsDep,
        db: DBSession,
        # Default-value form on purpose: this module uses ``from __future__ import annotations`` and
        # ``resolve_target`` is a closure variable, which FastAPI cannot see in a stringified ``Annotated``.
        resolved: Any = Depends(resolve_target),
    ) -> User:
        await grants.require(db, code, resolved)
        return user

    _guard.__name__ = f"perm[{code}]"
    setattr(_guard, MARKER, {"code": code, "has_target": target is not None})
    return Annotated[User, Depends(_guard)]


def org_of(model_path: str, *code_attrs: str, param: str = "ref") -> Callable[..., Any]:
    """Target factory: judge the action AT THE ORGANIZATION OF THE ROW the path names.

        Perm("geo.place:update", target=org_of("app.modules.geo.model:Place"))

    Without it a branch-A administrator could edit branch B's rows by sending ``X-Organization-Code: A``
    (the request organization is only the DEFAULT target). ``model_path`` is ``"module:Class"``, imported
    lazily so ``rbac`` never imports a feature module at import time. The row is found by uuid, numeric id,
    or any of ``code_attrs`` (the columns the module's own ``{ref}`` accepts); ``param`` names the path
    parameter when it is not ``ref``.

    A row that cannot be resolved (or has no organization — tenant-wide) yields no target, i.e. the
    request's organization; the handler then 404s or acts on a tenant-wide row exactly as before.
    """
    async def _target(request: Request, db: DBSession) -> Target | None:
        import importlib
        import uuid as uuid_lib

        from sqlalchemy import func, or_, select

        raw = request.path_params.get(param)
        if raw is None:
            return None
        module, _, name = model_path.partition(":")
        model = getattr(importlib.import_module(module), name)
        conds = []
        text = str(raw)
        if hasattr(model, "uuid"):
            try:
                conds.append(model.uuid == uuid_lib.UUID(text))
            except ValueError:
                pass
        if text.isdigit():
            conds.append(model.id == int(text))
        for attr in code_attrs:
            column = getattr(model, attr, None)
            if column is not None:
                conds.append(func.lower(column) == text.lower())
        if not conds:
            return None
        row = await db.scalar(select(model).where(or_(*conds)).limit(1))
        organization_id = getattr(row, "organization_id", None) if row is not None else None
        return Target(organization_id=organization_id) if organization_id is not None else None

    _target.__name__ = f"org_of[{model_path}]"
    return _target


__all__ = ["MARKER", "GrantsDep", "Perm", "Target", "get_grants", "org_of"]
