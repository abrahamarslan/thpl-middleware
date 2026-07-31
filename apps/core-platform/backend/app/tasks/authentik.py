"""Authentik sync retry tasks (queue: default).

When an inline Authentik sync fails during a request, the user service enqueues
one of these tasks so the mirror eventually catches up. They are the outer
safety net for transient Authentik outages.

Why a fresh engine + client per task
------------------------------------
The stack is asyncpg-only (no sync DB driver), so these synchronous Celery tasks
drive the async code via ``asyncio.run``. Each invocation gets its own event
loop, so it also gets a throwaway ``NullPool`` engine and a fresh
``AuthentikAdminClient`` — never the module-level singletons, whose connections
would be bound to an already-closed loop.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.security.authentik_client import AuthentikAdminClient, AuthentikError
from app.core.conf import settings
from app.modules.users import authentik_sync, crud
from app.modules.users.authentik_sync import SyncResult

logger = structlog.get_logger("app.tasks.authentik")

_RETRY_KW = dict(
    autoretry_for=(AuthentikError,),
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)


def _run(fn: Callable[[AsyncSession, AuthentikAdminClient], Awaitable[Any]]) -> Any:
    """Run ``fn`` with a throwaway async session + Authentik client (loop-safe)."""

    async def _scope() -> Any:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        client = AuthentikAdminClient()
        try:
            async with session_factory() as db:
                result = await fn(db, client)
                await db.commit()
                return result
        finally:
            await client.aclose()
            await engine.dispose()

    return asyncio.run(_scope())


@shared_task(bind=True, name="app.tasks.authentik.provision_user", **_RETRY_KW)
def provision_user(self, user_id: int) -> dict:
    """Create-or-link a user in Authentik (register/create-user fallback).

    Tries an email match first (idempotent re-run safety), otherwise creates the
    user with a random password and flags ``password_drift`` (the user resets to
    gain native-Authentik access; local app login is unaffected).
    """

    async def work(db: AsyncSession, client: AuthentikAdminClient) -> dict | None:
        user = await crud.get_by_id(db, user_id, include_deleted=True)
        if user is None:
            return None  # outer txn not committed yet — signal a retry
        if user.authentik_pk:
            return {"status": "already_linked", "authentik_pk": user.authentik_pk}

        existing = await client.find_by_email(user.email)
        if existing:
            authentik_sync.link_existing(user, existing)
            return {"status": "linked", "authentik_pk": user.authentik_pk}

        result = await authentik_sync.sync_create(db, user, None, client=client)
        return {"status": result.value}

    out = _run(work)
    if out is None:
        raise self.retry(countdown=15, exc=RuntimeError(f"user {user_id} not yet visible"))
    if out.get("status") == SyncResult.FAILED.value:
        raise self.retry(exc=AuthentikError("provision failed; retrying"))
    return out


@shared_task(bind=True, name="app.tasks.authentik.sync_profile", **_RETRY_KW)
def sync_profile(self, user_id: int, fields: list[str]) -> dict:
    async def work(db: AsyncSession, client: AuthentikAdminClient) -> dict | None:
        user = await crud.get_by_id(db, user_id, include_deleted=True)
        if user is None:
            return None
        result = await authentik_sync.sync_update_profile(db, user, set(fields), client=client)
        return {"status": result.value}

    out = _run(work)
    if out is None:
        raise self.retry(countdown=15, exc=RuntimeError(f"user {user_id} not yet visible"))
    if out.get("status") == SyncResult.FAILED.value:
        raise self.retry(exc=AuthentikError("profile sync failed; retrying"))
    return out


@shared_task(bind=True, name="app.tasks.authentik.sync_status", **_RETRY_KW)
def sync_status(self, user_id: int, is_active: bool) -> dict:
    async def work(db: AsyncSession, client: AuthentikAdminClient) -> dict | None:
        user = await crud.get_by_id(db, user_id, include_deleted=True)
        if user is None:
            return None
        result = await authentik_sync.sync_set_active(db, user, is_active, client=client)
        return {"status": result.value}

    out = _run(work)
    if out is None:
        raise self.retry(countdown=15, exc=RuntimeError(f"user {user_id} not yet visible"))
    if out.get("status") == SyncResult.FAILED.value:
        raise self.retry(exc=AuthentikError("status sync failed; retrying"))
    return out


@shared_task(bind=True, name="app.tasks.authentik.delete_user", **_RETRY_KW)
def delete_user(self, authentik_pk: str) -> dict:
    async def work(db: AsyncSession, client: AuthentikAdminClient) -> dict:
        result = await authentik_sync.sync_delete(authentik_pk, client=client)
        return {"status": result.value}

    out = _run(work)
    if out.get("status") == SyncResult.FAILED.value:
        raise self.retry(exc=AuthentikError("delete failed; retrying"))
    return out


@shared_task(name="app.tasks.authentik.backfill")
def backfill(limit: int = 500) -> dict:
    """One-shot/periodic: link or create Authentik users for every active local
    user that has no ``authentik_pk`` yet. Safe to re-run."""

    async def work(db: AsyncSession, client: AuthentikAdminClient) -> dict:
        users, _ = await crud.list_users(db, page=1, page_size=limit, order_by="id")
        linked = created = failed = skipped = 0
        for user in users:
            if user.authentik_pk:
                skipped += 1
                continue
            try:
                existing = await client.find_by_email(user.email)
                if existing:
                    authentik_sync.link_existing(user, existing)
                    linked += 1
                else:
                    result = await authentik_sync.sync_create(db, user, None, client=client)
                    created += 1 if result is SyncResult.OK else 0
                    failed += 1 if result is SyncResult.FAILED else 0
            except Exception as e:  # noqa: BLE001
                logger.error("authentik_backfill_user_failed", user_id=user.id, error=str(e))
                failed += 1
        return {"linked": linked, "created": created, "failed": failed, "skipped": skipped}

    summary = _run(work)
    logger.info("authentik_backfill_complete", **summary)
    return summary
