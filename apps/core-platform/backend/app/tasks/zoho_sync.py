"""Celery drivers for the Zoho Sync Engine (queue: integrations).

Async-in-Celery pattern (ADR‑3, app/tasks/_loop.py): every task runs on the
worker process's single long-lived event loop via ``run_async``, so the
pooled engine, ``redis_client``, the token store and the switches are shared
across tasks exactly as in the API process. Each task still gets its own
ZohoClient, because its default priority/module differ per lane.

Tasks:
  planner_tick          Beat, every minute — the ONLY scheduler (control/planner.py):
                        reaps dead leases, persists the quota day, enqueues due
                        lanes the switches and the governor allow
  sync_module_run       one leased engine run of one lane (scheduled / weekly_full /
                        manual); exits immediately if the lane is already running
  sync_module           operator/API trigger -> sync_module_run(lane="manual")
  fetch_detail          the N+1 fan-out worker (one record per task)
  retention_maintenance nightly partitions + policy purges (control/retention.py)
  sync_all_due          DEPRECATED alias of planner_tick (queued messages drain safely)
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import async_session_factory
from app.modules.zoho.core.client import ZohoClient
from app.modules.zoho.core.errors import (
    ZohoAmbiguousOutcome,
    ZohoAuthError,
    ZohoAuthRevokedError,
    ZohoCircuitOpenError,
    ZohoContractError,
    ZohoForbiddenError,
    ZohoNotFoundError,
    ZohoQuotaExhaustedError,
    ZohoRateLimitedError,
    ZohoTransientError,
    ZohoUnclassifiedError,
    ZohoValidationError,
)

logger = structlog.get_logger("app.tasks.zoho_sync")

# Celery retries only failures a later attempt can fix. ``ZohoApiError`` is now
# an alias of the base ``ZohoError`` (every Zoho failure), so it must never be
# used in ``autoretry_for`` again: that would blindly replay an AMBIGUOUS
# create — Zoho may already hold the record, and a replay duplicates it.
# Ambiguous creates are resolved by the outbox v2 identity lookup; until then
# they fail loudly and stay visible in zoho_queue_logs for an operator.
_RETRY_KW = dict(
    autoretry_for=(ZohoTransientError, ZohoRateLimitedError, ZohoCircuitOpenError, ZohoAuthError),
    dont_autoretry_for=(
        ZohoAmbiguousOutcome,
        ZohoQuotaExhaustedError,   # resumes next quota day, not in 60 s
        ZohoAuthRevokedError,      # needs a human to reconnect
        ZohoValidationError,
        ZohoNotFoundError,
        ZohoForbiddenError,
        ZohoContractError,
        ZohoUnclassifiedError,
    ),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)


#: A yielded full scan older than this restarts from page 1 instead of
#: stitching two different days' snapshots together (delta R16).
_SCAN_MAX_AGE_HOURS = 36


def _run(
    fn: Callable[[AsyncSession, ZohoClient], Awaitable[Any]],
    *,
    client_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run ``fn`` with a pooled session + a task-scoped Zoho client on the
    process loop (see module doc)."""
    from app.tasks._loop import run_async

    async def _scope() -> Any:
        client = ZohoClient(**(client_kwargs or {}))
        try:
            async with async_session_factory() as db:
                result = await fn(db, client)
                await db.commit()
                return result
        finally:
            await client.aclose()

    return run_async(_scope())


@shared_task(bind=True, name="app.tasks.zoho_sync.sync_module_run", **_RETRY_KW)
def sync_module_run(
    self,
    module_name: str,
    lane: str,
    mode: str | None = None,
    trigger: str = "planner",
    requested_by: int | None = None,
) -> dict:
    """One leased engine run of one lane.

    The lease (a row in zoho_sync_runs, unique while RUNNING) is committed
    before any Zoho call, so a duplicate enqueue finds the lane busy and exits.
    Budget refusals end the run as YIELDED/SUSPENDED without a Celery retry —
    the planner re-enqueues when the governor allows it again.
    """
    from app.modules.zoho.control.planner import LANE_PRIORITY

    return _run(
        lambda db, client: execute_leased_run(
            db, client, module_name=module_name, lane=lane, mode=mode, trigger=trigger,
            requested_by=requested_by, task_id=self.request.id,
        ),
        client_kwargs={"default_module": module_name,
                       **({"default_priority": LANE_PRIORITY[lane]} if lane in LANE_PRIORITY else {})},
    )


async def execute_leased_run(db: AsyncSession, client: ZohoClient, **kwargs: Any) -> dict:
    """Run one leased slice in the Zoho tenant's scope (control/tenancy.py):
    every row it writes belongs to that tenant, is attached to the Zoho
    organization node, and is stamped ``system:zoho-sync``."""
    from app.modules.zoho.control.tenancy import zoho_scope

    async with zoho_scope(db):
        return await _execute_leased_run(db, client, **kwargs)


async def _execute_leased_run(
    db: AsyncSession,
    client: ZohoClient,
    *,
    module_name: str,
    lane: str,
    mode: str | None,
    trigger: str,
    requested_by: int | None = None,
    task_id: str | None = None,
) -> dict:
    """Acquire the lane lease, run one engine slice, close the run. Testable
    without Celery (tests call it directly with a fake Zoho client).

    Each applied page is committed together with the lane cursor's
    ``next_page`` (fenced by this run's id) and the lease is heartbeated, so:
      * a crash, a budget stop or a governor refusal loses at most one page;
      * a yielded full scan resumes where it stopped (``start_page``);
      * a run that lost its lease stops at the next page boundary.
    """
    import time
    from datetime import UTC, datetime, timedelta

    from app.modules.zoho.control.models import RunStatus
    from app.modules.zoho.control.runs import (
        CursorFenced,
        acquire_run,
        advance_cursor,
        claim_cursor,
        finish_run,
        heartbeat,
        lease_owner,
        load_cursor,
    )
    from app.modules.zoho.core.errors import ZohoBudgetDeferred, ZohoQuotaExhaustedError
    from app.modules.zoho.sync.engine import SyncRunReport, ZohoSyncEngine

    run = await acquire_run(
        db, module=module_name, lane=lane, trigger=trigger, mode=mode,
        owner=lease_owner(task_id), requested_by=requested_by,
    )
    if run is None:
        logger.info("zoho.run.skipped", module=module_name, lane=lane, reason="lane_busy")
        return {"status": "skipped", "reason": "lane_busy"}

    # Resume a yielded scan of the SAME mode that is not too old (a scan paused
    # for a day would otherwise stitch two different snapshots together).
    cursor = await load_cursor(db, module=module_name, lane=lane)
    resumable = (
        cursor.next_page > 1
        and (cursor.state or {}).get("mode") == (mode or "configured")
        and cursor.scan_started_at is not None
        and datetime.now(UTC) - cursor.scan_started_at < timedelta(hours=_SCAN_MAX_AGE_HOURS)
    )
    start_page = cursor.next_page if resumable else 1
    scan_started_at = cursor.scan_started_at if resumable else datetime.now(UTC)
    await claim_cursor(db, run)
    await db.commit()

    async def on_page(report: SyncRunReport, next_page: int) -> None:
        await advance_cursor(
            db, run, next_page=next_page, scan_started_at=scan_started_at,
            state={"mode": mode or "configured", "last_page_at": datetime.now(UTC).isoformat()},
        )
        await db.commit()                                   # the page, its events and the cursor
        if not await heartbeat(db, run):
            raise CursorFenced(f"run {run.id} lost its lease")

    started = time.perf_counter()
    engine = ZohoSyncEngine(db, client, run_id=run.id)
    structlog.contextvars.bind_contextvars(run_id=str(run.id), module=module_name, lane=lane)

    def partial() -> dict:
        return engine.report.model_dump() if engine.report else {}

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        report = await engine.run(module_name, mode, start_page=start_page, page_hook=on_page)
        await db.commit()                                   # the last page + stats
    except CursorFenced as exc:
        await db.rollback()
        logger.warning("zoho.run.fenced_stop", run_id=str(run.id), error=str(exc))
        return {"status": RunStatus.ABANDONED, "run_id": str(run.id)}
    except ZohoQuotaExhaustedError as exc:
        await db.rollback()
        await finish_run(db, run, status=RunStatus.SUSPENDED, stop_reason="quota_exhausted",
                         counters=partial(), duration_ms=elapsed(), error=exc)
        return {"status": RunStatus.SUSPENDED, "run_id": str(run.id)}
    except ZohoBudgetDeferred as exc:                       # governor pacing/state or a switch
        await db.rollback()
        await finish_run(db, run, status=RunStatus.YIELDED, stop_reason=exc.reason[:64],
                         counters=partial(), duration_ms=elapsed())
        return {"status": RunStatus.YIELDED, "run_id": str(run.id), "reason": exc.reason}
    except Exception as exc:
        await db.rollback()
        await finish_run(db, run, status=RunStatus.FAILED, counters=partial(),
                         duration_ms=elapsed(), error=exc)
        raise
    finally:
        structlog.contextvars.unbind_contextvars("run_id", "lane")

    counters = report.model_dump()
    status = {
        "success": RunStatus.SUCCEEDED,
        "partial": RunStatus.PARTIAL,
        "yielded": RunStatus.YIELDED,
    }.get(report.status, RunStatus.SUCCEEDED)
    await finish_run(db, run, status=status, counters=counters, duration_ms=report.duration_ms,
                     stop_reason=report.stop_reason)
    return {**counters, "status": status, "run_id": str(run.id)}   # our status wins over the report's


@shared_task(name="app.tasks.zoho_sync.sync_module")
def sync_module(module_name: str, mode: str | None = None, requested_by: int | None = None) -> dict:
    """Operator/API trigger — a leased run on the ``manual`` lane."""
    result = sync_module_run.delay(module_name, "manual", mode, "api", requested_by)
    return {"queued": True, "task_id": result.id, "lane": "manual"}


@shared_task(bind=True, name="app.tasks.zoho_sync.fetch_detail", **_RETRY_KW)
def fetch_detail(self, module_name: str, zoho_id: str, queue_log_id: int | None = None) -> dict:
    """N+1 worker: fetch one full record and upsert it locally."""
    from app.modules.zoho.sync.engine import ZohoSyncEngine

    async def work(db: AsyncSession, client: ZohoClient) -> dict:
        from app.modules.zoho.control.tenancy import zoho_scope

        async with zoho_scope(db):
            engine = ZohoSyncEngine(db, client)
            return await engine.fetch_detail_and_upsert(
                module_name, zoho_id, queue_log_id=queue_log_id, attempt=self.request.retries
            )

    return _run(work)


@shared_task(name="app.tasks.zoho_sync.planner_tick")
def planner_tick() -> dict:
    """Beat, every minute: the single scheduler (see control/planner.py)."""
    from app.modules.zoho.control import planner

    def enqueue(module: str, lane: str, mode: str | None) -> None:
        sync_module_run.delay(module, lane, mode, "planner")

    async def work(db: AsyncSession, _client: ZohoClient) -> dict:
        from app.modules.zoho.control.tenancy import zoho_scope

        async with zoho_scope(db, "zoho-planner"):
            return await planner.tick(db, enqueue=enqueue)

    return _run(work)


@shared_task(name="app.tasks.zoho_sync.retention_maintenance")
def retention_maintenance() -> dict:
    """Nightly: create event partitions ahead, drop expired ones, apply policies."""
    from app.modules.zoho.control.retention import run_maintenance

    async def work(db: AsyncSession, _client: ZohoClient) -> dict:
        return await run_maintenance(db)

    return _run(work)


@shared_task(name="app.tasks.zoho_sync.sync_all_due")
def sync_all_due(force_mode: str | None = None, force: bool = False) -> dict:
    """DEPRECATED — replaced by ``planner_tick``. Kept so messages already in
    the broker (and an old Beat still running during deploy) drain harmlessly.
    ``force``/``force_mode`` are ignored: the weekly full is a planner lane."""
    logger.warning("zoho.planner.deprecated_dispatcher_called", force_mode=force_mode, force=force)
    return planner_tick()
