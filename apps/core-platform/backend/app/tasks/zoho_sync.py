"""Celery drivers for the Zoho Sync Engine (queue: integrations).

Async-in-Celery pattern (same rationale as app/tasks/authentik.py): the stack
is asyncpg-only, so each task runs the async engine via ``asyncio.run`` with:

  - a throwaway NullPool engine + session (never the API's pooled engine —
    its connections belong to a different event loop);
  - a FRESH ZohoClient (its httpx pool must live and die with this loop);
  - a final ``redis_client.aclose()``: the Zoho guard rails (token manager,
    rate limiter, circuit breaker) use the shared async Redis singleton, and
    disconnecting its pool at loop teardown prevents "attached to a different
    loop" errors on the next task. The pool transparently reconnects.

Tasks:
  sync_module     one engine run (full / incremental / index)
  fetch_detail    the N+1 fan-out worker (one record per task)
  push_outbound   the outbox executor (local -> Zoho create/update/delete)
  sync_all_due    beat dispatcher — enqueues sync_module for every module
                  whose sync_interval_minutes has elapsed (config-driven
                  scheduling; no per-module beat entries needed)
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.exception.errors import NotFoundError
from app.core.conf import settings
from app.modules.zoho.core.client import ZohoClient
from app.modules.zoho.core.exceptions import ZohoApiError, ZohoCircuitOpenError, ZohoRateLimitedError

logger = structlog.get_logger("app.tasks.zoho_sync")

_RETRY_KW = dict(
    autoretry_for=(ZohoApiError, ZohoRateLimitedError, ZohoCircuitOpenError),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)


def _run(fn: Callable[[AsyncSession, ZohoClient], Awaitable[Any]]) -> Any:
    """Run ``fn`` with a loop-scoped session + Zoho client (see module doc)."""

    async def _scope() -> Any:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        client = ZohoClient()
        try:
            async with session_factory() as db:
                result = await fn(db, client)
                await db.commit()
                return result
        finally:
            await client.aclose()
            await engine.dispose()
            from app.database.redis import redis_client

            await redis_client.aclose()  # drop loop-bound pooled connections

    return asyncio.run(_scope())


@shared_task(bind=True, name="app.tasks.zoho_sync.sync_module", **_RETRY_KW)
def sync_module(self, module_name: str, mode: str | None = None) -> dict:
    """One inbound sync run for a registered module."""
    from app.modules.zoho.sync.engine import ZohoSyncEngine

    async def work(db: AsyncSession, client: ZohoClient) -> dict:
        report = await ZohoSyncEngine(db, client).run(module_name, mode)
        return report.model_dump()

    return _run(work)


@shared_task(bind=True, name="app.tasks.zoho_sync.fetch_detail", **_RETRY_KW)
def fetch_detail(self, module_name: str, zoho_id: str, queue_log_id: int | None = None) -> dict:
    """N+1 worker: fetch one full record and upsert it locally."""
    from app.modules.zoho.sync.engine import ZohoSyncEngine

    async def work(db: AsyncSession, client: ZohoClient) -> dict:
        engine = ZohoSyncEngine(db, client)
        return await engine.fetch_detail_and_upsert(
            module_name, zoho_id, queue_log_id=queue_log_id, attempt=self.request.retries
        )

    return _run(work)


@shared_task(bind=True, name="app.tasks.zoho_sync.push_outbound", **_RETRY_KW)
def push_outbound(self, module_name: str, local_id: int, op: str, queue_log_id: int | None = None) -> dict:
    """Outbox executor — see app/modules/zoho/sync/outbox.py."""
    from app.modules.zoho.sync import outbox

    async def work(db: AsyncSession, client: ZohoClient) -> dict:
        return await outbox.push_record(
            db, client, module_name, local_id, op,
            queue_log_id=queue_log_id, attempt=self.request.retries,
        )

    try:
        return _run(work)
    except NotFoundError as e:
        # Enqueued before the caller's transaction committed — retry shortly.
        raise self.retry(countdown=10, exc=e, max_retries=6)


@shared_task(name="app.tasks.zoho_sync.sync_all_due")
def sync_all_due(force_mode: str | None = None, force: bool = False) -> dict:
    """Beat dispatcher: enqueue a sync for every module whose interval elapsed.

    Config-driven scheduling — modules declare ``sync_interval_minutes`` and
    this single beat entry honours it, instead of one hardcoded beat entry per
    module. ``force=True`` (weekly full-sync safety net) ignores intervals.
    """
    from app.modules.zoho.sync.config import SyncDirection
    from app.modules.zoho.sync.models import ZohoSyncStat
    from app.modules.zoho.sync.registry import sync_registry

    async def work(db: AsyncSession, _client: ZohoClient) -> dict:
        stats = {s.module_name: s for s in (await db.scalars(select(ZohoSyncStat))).all()}
        queued: list[str] = []
        now = datetime.now(UTC)
        for defn in sync_registry.all():
            cfg = defn.config
            if not cfg.enabled or cfg.direction in (SyncDirection.DISABLED, SyncDirection.OUTBOUND):
                continue
            stat = stats.get(defn.name)
            due = force or stat is None or stat.last_sync_time is None or (
                (now - stat.last_sync_time).total_seconds() >= cfg.sync_interval_minutes * 60
            )
            if due:
                sync_module.delay(defn.name, force_mode)
                queued.append(defn.name)
        return {"queued": queued, "mode": force_mode or "configured"}

    summary = _run(work)
    logger.info("zoho_sync_dispatch", **summary)
    return summary
