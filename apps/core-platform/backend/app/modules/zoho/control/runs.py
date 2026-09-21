"""Run leases and fenced cursors — crash-safe exclusion without TTL guessing.

Guarantees (docs/zoho-sync-implementation/control-plane.md §3):
  * **At most one running run per module × lane**, enforced by the partial
    unique index ``uq_zoho_sync_runs_one_running``. Two workers racing to start
    the same lane: one INSERT wins, the other gets ``None`` and exits.
  * **A dead worker never blocks a lane forever.** Its lease expires; the next
    acquirer marks the stale row ``abandoned`` and takes over.
  * **A zombie cannot corrupt progress.** Cursor writes carry the run id
    (``owner_run_id``); a run that lost its lease updates zero rows and learns
    it has been fenced.
  * Lease rows are committed in their **own** transaction so other workers see
    them immediately — never inside the long-running sync transaction.

These replace the Redis TTL lock and ``ShouldBeUnique`` patterns the PHP
engine used (lock expiring mid-run, redelivery races).
"""

from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.tenancy import write_tenant_id
from app.modules.zoho.control.models import RunStatus, ZohoSyncCursor, ZohoSyncRun
from app.modules.zoho.core.errors import ZohoError

logger = structlog.get_logger("app.zoho.runs")


_COUNTER_FIELDS = (
    "pages", "listed", "created", "updated", "resurrected", "unchanged", "stale_ignored",
    "skipped", "errors", "soft_deleted", "queued_details", "details_saved", "start_page", "next_page",
)


def lease_owner(task_id: str | None = None) -> str:
    """Human-readable owner: host:pid[:celery task id]."""
    owner = f"{socket.gethostname()}:{os.getpid()}"
    return f"{owner}:{task_id}" if task_id else owner


@dataclass(slots=True)
class RunHandle:
    id: uuid.UUID
    module: str
    lane: str
    owner: str


async def acquire_run(
    db: AsyncSession,
    *,
    module: str,
    lane: str,
    trigger: str,
    mode: str | None = None,
    owner: str | None = None,
    lease_seconds: int | None = None,
    requested_by: int | None = None,
    overrides: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> RunHandle | None:
    """Start a run, or return ``None`` if another live run holds the lane.

    Commits on success so the lease is visible to every other worker at once.
    """
    owner = owner or lease_owner()
    lease = timedelta(seconds=lease_seconds or settings.ZOHO_RUN_LEASE_SECONDS)
    tenant_id = await write_tenant_id(db)            # Core INSERT: no flush stamping

    for attempt in (1, 2):
        now = datetime.now(UTC)
        run_id = uuid.uuid4()
        try:
            await db.execute(
                pg_insert(ZohoSyncRun).values(
                    id=run_id, tenant_id=tenant_id, module=module, lane=lane, trigger=trigger, mode=mode,
                    status=RunStatus.RUNNING, lease_owner=owner, lease_expires_at=now + lease,
                    heartbeat_at=now, started_at=now, requested_by=requested_by,
                    overrides=overrides, request_id=request_id,
                )
            )
            await db.commit()
            logger.info("zoho.run.started", run_id=str(run_id), module=module, lane=lane,
                        trigger=trigger, mode=mode, owner=owner)
            return RunHandle(id=run_id, module=module, lane=lane, owner=owner)
        except IntegrityError:
            await db.rollback()

        # Someone holds the lane. If their lease expired, they are dead: take over.
        if attempt == 1 and await _abandon_expired(db, module=module, lane=lane):
            continue
        return None
    return None


async def _abandon_expired(db: AsyncSession, *, module: str, lane: str) -> bool:
    result = await db.execute(
        update(ZohoSyncRun)
        .where(
            ZohoSyncRun.module == module,
            ZohoSyncRun.lane == lane,
            ZohoSyncRun.status == RunStatus.RUNNING,
            ZohoSyncRun.lease_expires_at < func.now(),
        )
        .values(status=RunStatus.ABANDONED, finished_at=func.now(), stop_reason="lease_expired")
        .returning(ZohoSyncRun.id, ZohoSyncRun.lease_owner)
    )
    abandoned = result.all()
    await db.commit()
    for run_id, owner in abandoned:
        logger.warning("zoho.run.abandoned", run_id=str(run_id), module=module, lane=lane, owner=owner)
    return bool(abandoned)


async def heartbeat(db: AsyncSession, run: RunHandle, *, lease_seconds: int | None = None) -> bool:
    """Extend the lease. ``False`` means the run was fenced (someone took over)."""
    lease = timedelta(seconds=lease_seconds or settings.ZOHO_RUN_LEASE_SECONDS)
    result = await db.execute(
        update(ZohoSyncRun)
        .where(ZohoSyncRun.id == run.id, ZohoSyncRun.status == RunStatus.RUNNING,
               ZohoSyncRun.lease_owner == run.owner)
        .values(heartbeat_at=func.now(), lease_expires_at=func.now() + lease)
    )
    await db.commit()
    alive = result.rowcount == 1
    if not alive:
        logger.warning("zoho.run.fenced", run_id=str(run.id), module=run.module, lane=run.lane)
    return alive


async def finish_run(
    db: AsyncSession,
    run: RunHandle,
    *,
    status: str,
    counters: dict[str, int] | None = None,
    duration_ms: int | None = None,
    stop_reason: str | None = None,
    error: BaseException | None = None,
) -> None:
    """Close the run (own transaction). Only the lease owner may close it."""
    values: dict[str, Any] = {
        "status": status,
        "finished_at": func.now(),
        "duration_ms": duration_ms,
        "stop_reason": stop_reason,
    }
    # Only the known counter columns: callers pass whole engine reports, which
    # also carry "module"/"status"/"mode" (ERRORS E13).
    counted = {key: int(counters[key] or 0) for key in _COUNTER_FIELDS if counters and key in counters}
    values.update(counted)
    if error is not None:
        if isinstance(error, ZohoError):
            values.update(
                error_category=str(error.category),
                error_fingerprint=error.fingerprint(),
                error_message=error.msg[:2000],
            )
        else:
            values.update(error_category="bug", error_message=f"{type(error).__name__}: {error}"[:2000])

    result = await db.execute(
        update(ZohoSyncRun)
        .where(ZohoSyncRun.id == run.id, ZohoSyncRun.lease_owner == run.owner,
               ZohoSyncRun.status == RunStatus.RUNNING)
        .values(**values)
    )
    await db.commit()
    if result.rowcount != 1:
        logger.warning("zoho.run.finish_fenced", run_id=str(run.id), status=status)
        return
    log = logger.error if status == RunStatus.FAILED else logger.info
    log("zoho.run.finished", run_id=str(run.id), module=run.module, lane=run.lane,
        status=status, duration_ms=duration_ms, stop_reason=stop_reason, **counted)


async def reap_expired(db: AsyncSession) -> int:
    """Mark every expired RUNNING lease abandoned (planner housekeeping)."""
    result = await db.execute(
        update(ZohoSyncRun)
        .where(ZohoSyncRun.status == RunStatus.RUNNING, ZohoSyncRun.lease_expires_at < func.now())
        .values(status=RunStatus.ABANDONED, finished_at=func.now(), stop_reason="lease_expired")
        .returning(ZohoSyncRun.id, ZohoSyncRun.module, ZohoSyncRun.lane)
    )
    rows = result.all()
    await db.commit()
    for run_id, module, lane in rows:
        logger.warning("zoho.run.abandoned", run_id=str(run_id), module=module, lane=lane, owner=None)
    return len(rows)


async def running_count(db: AsyncSession) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(ZohoSyncRun).where(ZohoSyncRun.status == RunStatus.RUNNING)
    ) or 0)


async def last_finished(db: AsyncSession, *, module: str, lane: str) -> ZohoSyncRun | None:
    """Most recent completed run of a lane (drives "is it due?")."""
    return await db.scalar(
        select(ZohoSyncRun)
        .where(
            ZohoSyncRun.module == module,
            ZohoSyncRun.lane == lane,
            ZohoSyncRun.status.in_(
                [RunStatus.SUCCEEDED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.YIELDED]
            ),
        )
        .order_by(ZohoSyncRun.started_at.desc())
        .limit(1)
    )


async def is_running(db: AsyncSession, *, module: str, lane: str) -> bool:
    return bool(await db.scalar(
        select(func.count()).select_from(ZohoSyncRun).where(
            and_(ZohoSyncRun.module == module, ZohoSyncRun.lane == lane,
                 ZohoSyncRun.status == RunStatus.RUNNING,
                 ZohoSyncRun.lease_expires_at >= func.now())
        )
    ))


# ── cursors ─────────────────────────────────────────────────────────────────

async def load_cursor(db: AsyncSession, *, module: str, lane: str) -> ZohoSyncCursor:
    cursor = await db.get(ZohoSyncCursor, (module, lane))
    if cursor is None:
        await db.execute(
            pg_insert(ZohoSyncCursor).values(tenant_id=await write_tenant_id(db), module=module, lane=lane,
                                             next_page=1, state={})
            .on_conflict_do_nothing(index_elements=["module", "lane"])
        )
        cursor = await db.get(ZohoSyncCursor, (module, lane))
    return cursor


async def claim_cursor(db: AsyncSession, run: RunHandle) -> None:
    """Make ``run`` the only writer of its lane's cursor (fencing token)."""
    await load_cursor(db, module=run.module, lane=run.lane)
    await db.execute(
        update(ZohoSyncCursor)
        .where(ZohoSyncCursor.module == run.module, ZohoSyncCursor.lane == run.lane)
        .values(owner_run_id=run.id)
    )


class CursorFenced(RuntimeError):
    """The run no longer owns the cursor (or its lease) — another run took the lane over."""


async def advance_cursor(db: AsyncSession, run: RunHandle, **fields: Any) -> None:
    """Fenced cursor update — call inside the same transaction as the applied page."""
    result = await db.execute(
        update(ZohoSyncCursor)
        .where(ZohoSyncCursor.module == run.module, ZohoSyncCursor.lane == run.lane,
               ZohoSyncCursor.owner_run_id == run.id)
        .values(**fields, updated_at=func.now())
    )
    if result.rowcount != 1:
        raise CursorFenced(f"run {run.id} no longer owns cursor {run.module}/{run.lane}")


__all__ = [
    "CursorFenced",
    "RunHandle",
    "acquire_run",
    "advance_cursor",
    "claim_cursor",
    "finish_run",
    "heartbeat",
    "is_running",
    "last_finished",
    "lease_owner",
    "load_cursor",
    "reap_expired",
    "running_count",
]
