"""Evaluating permissions OUTSIDE an HTTP request — Celery tasks, FastStream/Kafka consumers, CLIs.

Background work has no ``CurrentUser`` and no ``X-Organization-Code``. The rule
(docs/rbac-module.md §4.9) is one sentence per case:

1. **Services do not authorize.** The HTTP edge decides (``rbac.deps.Perm``); a service called by
   a task is trusted code.
2. **System jobs** (Zoho sync, retention, cron) run as ``system:<component>`` — ``system_scope``.
   They are not evaluated against RBAC and must never take a permission decision from message
   contents.
3. **User-initiated background work** (a PDF export, an import, a bulk action) carries the
   *actor's id* in its payload — **never credentials, never a permission decision** — and the task
   re-evaluates at EXECUTION time with ``acting_as`` / ``check_actor``. A grant revoked while the
   job waited in the queue therefore stops the job; the enqueue-time check on the route only
   fails fast.
4. **Message consumers** (Kafka) are system actors (case 2). A message that asks for something a
   user is entitled to do must carry the actor id and go through case 3.

Everything here binds the tenancy context (tenant, organization, actor) exactly like a request,
so rows written by the task are stamped with the right ``created_by``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ForbiddenError
from app.database.tenancy import Actor, system_actor, tenant_scope
from app.modules.rbac import engine
from app.modules.rbac.engine import Grants, Target


@dataclass(slots=True)
class ActingUser:
    user: Any
    grants: Grants

    async def require(self, db: AsyncSession, code: str, target: Target | None = None) -> None:
        await self.grants.require(db, code, target)


@contextmanager
def system_scope(component: str, *, tenant_id: int | None = None, organization_id: int | None = None) -> Iterator[None]:
    """Run trusted system work: ``created_by_name = 'system:<component>'``, no RBAC evaluation."""
    with tenant_scope(tenant_id, organization_id, system_actor(component)):
        yield


@asynccontextmanager
async def acting_as(
    db: AsyncSession, user_id: int, *, organization_id: int | None = None,
) -> AsyncIterator[ActingUser]:
    """Bind the tenancy context to ``user_id`` and yield their grants (case 3).

    Refuses (403) a user who no longer exists or may no longer use the API — the same states
    ``get_current_user`` refuses.
    """
    from app.modules.users.model import User

    user = await db.scalar(select(User).where(User.id == user_id).execution_options(all_tenants=True))
    if (
        user is None or user.deleted_at is not None
        or bool(user.is_deactivated) or bool(user.is_banned)
    ):
        raise ForbiddenError("The user who started this job can no longer act", data={"user_id": user_id})
    name = str(user.name or user.email or f"user:{user.id}")[:255]
    with tenant_scope(user.tenant_id, organization_id or user.organization_id, Actor(user.id, name)):
        yield ActingUser(user=user, grants=await engine.load_grants(db, user))


async def check_actor(
    db: AsyncSession, user_id: int, code: str, target: Target | None = None,
    *, organization_id: int | None = None,
) -> None:
    """One-shot re-check for a task: raise ``ForbiddenError`` unless ``user_id`` holds ``code`` now."""
    async with acting_as(db, user_id, organization_id=organization_id) as actor:
        await actor.require(db, code, target)


__all__ = ["ActingUser", "acting_as", "check_actor", "system_scope"]
