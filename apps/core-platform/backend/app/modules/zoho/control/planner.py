"""The planner — the single scheduler for every Zoho pull run.

Replaces the v1 Beat entries ``zoho-sync-dispatcher`` (every 5 min, no
"already running" guard — overlapping runs) and ``zoho-full-sync-weekly``
(forced full of every module at the same moment).

One Beat tick (every minute) calls :func:`tick`, which:
  1. reaps runs whose lease expired (dead workers);
  2. reseeds the governor from ``zoho_quota_days`` if Redis lost today's
     counters, then snapshots it and persists the quota day to Postgres;
  3. reads the engine switches, the runtime module config and write pressure
     (CDC slot lag, broker queue depth);
  4. asks the pure :func:`plan` what is due and allowed, and enqueues it —
     including **continuations** of slices that yielded;
  5. publishes a health snapshot for ``/metrics`` and the operator API.

Why this shape (docs/zoho-sync-implementation/control-plane.md §4):
  * **Due is computed from the last run in Postgres**, so a restart or a long
    outage produces one catch-up run per lane, never a burst of missed ones.
  * **The planner never runs work**; it only enqueues. Exclusion is the run
    lease's job, so a duplicate enqueue is harmless (the second worker finds
    the lane busy and exits).
  * **Budget-aware**: lanes whose priority the governor currently pauses are
    skipped with a reason instead of being queued to fail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.zoho.control.models import RunStatus, ZohoQuotaDay, ZohoSyncRun
from app.modules.zoho.control.runs import reap_expired
from app.modules.zoho.control.switches import SwitchState, zoho_switches
from app.modules.zoho.core.governor import GovernorState, Priority, zoho_governor
from app.modules.zoho.core.pacing import load_timezone

logger = structlog.get_logger("app.zoho.planner")

HEALTH_KEY = "zoho:health"
LANE_SCHEDULED = "scheduled"
LANE_WEEKLY_FULL = "weekly_full"
LANE_MANUAL = "manual"

LANE_PRIORITY: dict[str, Priority] = {
    LANE_SCHEDULED: Priority.INCREMENTAL,
    LANE_WEEKLY_FULL: Priority.RECONCILE,
    LANE_MANUAL: Priority.REFRESH,
}


@dataclass(frozen=True, slots=True)
class ModuleView:
    """What the planner needs to know about a registered module."""

    name: str
    enabled: bool
    pulls: bool                    # direction includes inbound
    interval_minutes: int
    strategy: str                  # configured engine strategy
    weekly_full_enabled: bool = True


@dataclass(frozen=True, slots=True)
class Continuation:
    """A lane whose last slice yielded: resume it, same mode, from ``due_at``."""

    mode: str | None
    due_at: datetime
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedRun:
    module: str
    lane: str
    mode: str | None
    priority: Priority
    overdue_seconds: float


@dataclass(frozen=True, slots=True)
class Skip:
    module: str
    lane: str
    reason: str


@dataclass(slots=True)
class Plan:
    runs: list[PlannedRun] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)


def _weekly_slot_start(now_local: datetime, weekday: int, hour: int) -> datetime:
    """The most recent weekly full-sync slot at or before ``now_local``.

    A slot missed during downtime is still the "most recent" one, so exactly
    one catch-up run happens — never one per missed week.
    """
    days_back = (now_local.weekday() - weekday) % 7
    slot = (now_local - timedelta(days=days_back)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if slot > now_local:
        slot -= timedelta(days=7)
    return slot


def plan(
    modules: list[ModuleView],
    *,
    last_started: dict[tuple[str, str], datetime],
    running: set[tuple[str, str]],
    running_count: int,
    switches: SwitchState,
    governor_state: GovernorState,
    now: datetime,
    timezone: str = "Asia/Kolkata",
    weekly_weekday: int = 6,
    weekly_hour: int = 3,
    max_concurrent_runs: int = 2,
    continuations: dict[tuple[str, str], Continuation] | None = None,
    write_pressure: str | None = None,
) -> Plan:
    """Decide which lanes to enqueue. Pure: no I/O, fully table-testable."""
    result = Plan()
    continuations = continuations or {}
    now_local = now.astimezone(load_timezone(timezone))
    weekly_slot = _weekly_slot_start(now_local, weekly_weekday, weekly_hour)

    candidates: list[PlannedRun] = []
    for module in modules:
        lanes: list[tuple[str, str | None, float | None]] = []

        # Scheduled lane: every interval_minutes since the last start.
        last = last_started.get((module.name, LANE_SCHEDULED))
        interval = timedelta(minutes=max(module.interval_minutes, 1))
        overdue = (now - last - interval).total_seconds() if last else interval.total_seconds()
        lanes.append((LANE_SCHEDULED, None, overdue if overdue >= 0 else None))

        # Weekly full lane: once per week after the slot, only when the module
        # is not already on a full strategy (that would be the same run twice).
        if module.strategy != "full" and module.weekly_full_enabled:
            last_full = last_started.get((module.name, LANE_WEEKLY_FULL))
            slot_utc = weekly_slot.astimezone(UTC)
            due = last_full is None or last_full < slot_utc
            lanes.append((LANE_WEEKLY_FULL, "full", (now - slot_utc).total_seconds() if due else None))

        # Continuations: a lane whose last slice yielded resumes (same mode)
        # once its backoff has passed — before its normal schedule says so.
        planned = {lane for lane, _, _ in lanes}
        for lane in (LANE_SCHEDULED, LANE_WEEKLY_FULL, LANE_MANUAL):
            cont = continuations.get((module.name, lane))
            if cont is None:
                continue
            overdue_s = (now - cont.due_at).total_seconds()
            if lane in planned:
                lanes = [(ln, cont.mode if ln == lane else md,
                          (overdue_s if overdue_s >= 0 else od) if ln == lane else od)
                         for ln, md, od in lanes]
            elif overdue_s >= 0:
                lanes.append((lane, cont.mode, overdue_s))

        for lane, mode, overdue_s in lanes:
            if overdue_s is None:
                continue                                   # not due
            reason = _refusal(module, lane, switches, governor_state, running)
            if reason is None and write_pressure:
                reason = f"write_pressure:{write_pressure}"
            if reason:
                result.skipped.append(Skip(module.name, lane, reason))
                continue
            candidates.append(PlannedRun(module.name, lane, mode, LANE_PRIORITY[lane], overdue_s))

    # Freshness first, then the most overdue; respect the global run cap.
    candidates.sort(key=lambda r: (r.priority, -r.overdue_seconds))
    capacity = max(max_concurrent_runs - running_count, 0)
    for run in candidates:
        if capacity > 0:
            result.runs.append(run)
            capacity -= 1
        else:
            result.skipped.append(Skip(run.module, run.lane, "concurrency_cap"))
    return result


def _refusal(
    module: ModuleView,
    lane: str,
    switches: SwitchState,
    governor_state: GovernorState,
    running: set[tuple[str, str]],
) -> str | None:
    if not module.enabled or not module.pulls:
        return "module_disabled"
    reason = switches.refusal(direction="pull", module=module.name, interactive=False)
    if reason:
        return f"switch:{reason}"
    if LANE_PRIORITY[lane] > governor_state.max_rank:
        return f"governor:{governor_state}"
    if (module.name, lane) in running:
        return "lane_running"
    return None


# ── the async tick ──────────────────────────────────────────────────────────

async def registered_modules(db: AsyncSession | None = None) -> list[ModuleView]:
    """Every registered module as the planner sees it — with runtime overrides
    (config resolver) applied when a session is given."""
    from app.modules.zoho.control.config import zoho_config
    from app.modules.zoho.sync.config import SyncDirection
    from app.modules.zoho.sync.registry import sync_registry

    views = []
    for defn in sync_registry.all():
        cfg = await zoho_config.effective(db, defn) if db is not None else defn.config
        views.append(
            ModuleView(
                name=defn.name,
                enabled=cfg.enabled and cfg.direction is not SyncDirection.DISABLED,
                pulls=cfg.direction in (SyncDirection.INBOUND, SyncDirection.BIDIRECTIONAL),
                interval_minutes=cfg.sync_interval_minutes,
                strategy=cfg.strategy.value,
                weekly_full_enabled=cfg.weekly_full_enabled,
            )
        )
    return views


@dataclass(slots=True)
class RunHistory:
    last_started: dict[tuple[str, str], datetime]
    running: set[tuple[str, str]]
    continuations: dict[tuple[str, str], Continuation]

    @property
    def running_count(self) -> int:
        return len(self.running)


async def _run_history(db: AsyncSession, *, now: datetime | None = None) -> RunHistory:
    """Per lane: last start (abandoned/suspended excluded — the work did not
    complete), whether it is running, and whether its latest slice yielded."""
    now = now or datetime.now(UTC)
    rows = (await db.execute(
        select(ZohoSyncRun.module, ZohoSyncRun.lane, ZohoSyncRun.status, ZohoSyncRun.started_at,
               ZohoSyncRun.finished_at, ZohoSyncRun.mode, ZohoSyncRun.stop_reason)
        .where(ZohoSyncRun.started_at >= now - timedelta(days=8))
        .order_by(ZohoSyncRun.started_at)
    )).all()
    last_started: dict[tuple[str, str], datetime] = {}
    running: set[tuple[str, str]] = set()
    latest: dict[tuple[str, str], Any] = {}
    for row in rows:
        key = (row.module, row.lane)
        if row.status == RunStatus.RUNNING:
            running.add(key)
            continue
        latest[key] = row                                # rows are oldest → newest
        if row.status in (RunStatus.ABANDONED, RunStatus.SUSPENDED):
            continue
        if key not in last_started or row.started_at > last_started[key]:
            last_started[key] = row.started_at

    backoff = timedelta(seconds=settings.ZOHO_CONTINUATION_BACKOFF_SECONDS)
    continuations: dict[tuple[str, str], Continuation] = {}
    for key, row in latest.items():
        if row.status != RunStatus.YIELDED or key in running:
            continue
        reason = row.stop_reason or ""
        finished = row.finished_at or row.started_at
        # A budget stop is the slice model working: continue at once. A
        # governor/switch refusal waits, so a paused engine is not re-polled.
        due_at = finished if reason.startswith("budget:") else finished + backoff
        continuations[key] = Continuation(mode=row.mode, due_at=due_at, reason=reason or None)
    return RunHistory(last_started, running, continuations)


async def persist_quota_day(db: AsyncSession, snapshot: dict[str, Any]) -> None:
    """Durable copy of the governor's day counters (survives Redis loss)."""
    from app.database.tenancy import write_tenant_id

    values = {
        "tenant_id": await write_tenant_id(db),
        "pool": snapshot["pool"],
        "day": snapshot["day"],
        "used": snapshot["used"],
        "used_background": snapshot["used_background"],
        "reserved_peak": snapshot["reserved"],
        "state": snapshot["state"],
        "exhausted": snapshot["state"] == GovernorState.EXHAUSTED,
        "daily_hard_limit": snapshot["daily_hard_limit"],
    }
    stmt = pg_insert(ZohoQuotaDay).values(**values)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["pool", "day"],
            set_={
                # never let a Redis reset lower the durable count
                "used": func_greatest(ZohoQuotaDay.used, stmt.excluded.used),
                "used_background": func_greatest(ZohoQuotaDay.used_background, stmt.excluded.used_background),
                "reserved_peak": func_greatest(ZohoQuotaDay.reserved_peak, stmt.excluded.reserved_peak),
                "state": stmt.excluded.state,
                "exhausted": ZohoQuotaDay.exhausted | stmt.excluded.exhausted,
                "daily_hard_limit": stmt.excluded.daily_hard_limit,
            },
        )
    )


def func_greatest(a, b):
    from sqlalchemy import func

    return func.greatest(a, b)


async def reseed_governor(db: AsyncSession, *, now: datetime | None = None) -> bool:
    """After a Redis loss, raise today's governor counters back to what
    Postgres recorded — so a flushed Redis cannot hand out the day again."""
    day = zoho_governor.current_day(now)
    durable = await db.get(ZohoQuotaDay, (zoho_governor.config.pool, day.key))
    if durable is None:
        return False
    return await zoho_governor.reseed(
        used=durable.used, used_background=durable.used_background,
        exhausted=durable.exhausted, now=now,
    )


async def write_pressure(db: AsyncSession) -> str | None:
    """Why background lanes should hold off, or None.

    * CDC: the largest lag of an ACTIVE logical replication slot (Debezium).
      A 50k-row reconcile otherwise piles WAL behind a slow consumer and delays
      search/Soketi. Inactive slots are ignored — pausing Zoho does not help a
      stopped connector, and it must not block the business.
    * Broker: depth of the ``integrations`` Celery queue.
    Any probe that fails counts as "no pressure" (the planner must keep going).
    """
    max_lag_mb = settings.ZOHO_WRITE_PRESSURE_MAX_SLOT_LAG_MB
    if max_lag_mb:
        try:
            lag = await db.scalar(text(
                "SELECT max(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) "
                "FROM pg_replication_slots WHERE slot_type = 'logical' AND active"
            ))
            if lag is not None and float(lag) > max_lag_mb * 1024 * 1024:
                return f"cdc_lag_{int(float(lag) / 1048576)}mb"
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.debug("zoho.planner.slot_lag_probe_failed", error=str(exc))

    max_depth = settings.ZOHO_WRITE_PRESSURE_MAX_QUEUE_DEPTH
    if max_depth:
        from redis import asyncio as aioredis

        broker = aioredis.from_url(settings.CELERY_BROKER_URL)
        try:
            depth = int(await broker.llen("integrations"))
            if depth > max_depth:
                return f"queue_depth_{depth}"
        except Exception as exc:  # noqa: BLE001
            logger.debug("zoho.planner.queue_probe_failed", error=str(exc))
        finally:
            await broker.aclose()
    return None


async def tick(db: AsyncSession, *, enqueue, now: datetime | None = None) -> dict[str, Any]:
    """One planner pass. ``enqueue(module, lane, mode)`` sends the Celery task."""
    now = now or datetime.now(UTC)
    if not settings.ZOHO_PLANNER_ENABLED:
        logger.info("zoho.planner.disabled")
        return {"enabled": False}

    reaped = await reap_expired(db)
    try:
        await reseed_governor(db, now=now)
    except Exception as exc:  # noqa: BLE001 — never let the reseed stop planning
        await db.rollback()
        logger.error("zoho.planner.governor_reseed_failed", error=str(exc))
    governor = await zoho_governor.snapshot(now=now)
    try:
        await persist_quota_day(db, governor)
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — quota persistence must not stop planning
        await db.rollback()
        logger.error("zoho.planner.quota_persist_failed", error=str(exc))

    switches = await zoho_switches.snapshot()
    history = await _run_history(db, now=now)
    pressure = await write_pressure(db)
    decision = plan(
        await registered_modules(db),
        last_started=history.last_started,
        running=history.running,
        running_count=history.running_count,
        switches=switches,
        governor_state=GovernorState(governor["state"]),
        now=now,
        timezone=settings.ZOHO_QUOTA_DAY_TIMEZONE,
        weekly_weekday=settings.ZOHO_WEEKLY_FULL_WEEKDAY,
        weekly_hour=settings.ZOHO_WEEKLY_FULL_HOUR,
        max_concurrent_runs=settings.ZOHO_PLANNER_MAX_CONCURRENT_RUNS,
        continuations=history.continuations,
        write_pressure=pressure,
    )

    for run in decision.runs:
        enqueue(run.module, run.lane, run.mode)

    summary = {
        "at": now.isoformat(),
        "enqueued": [f"{r.module}/{r.lane}" for r in decision.runs],
        "skipped": {f"{s.module}/{s.lane}": s.reason for s in decision.skipped},
        "reaped": reaped,
        "running": history.running_count,
        "continuations": sorted(f"{m}/{lane}" for m, lane in history.continuations),
        "write_pressure": pressure,
        "governor_state": governor["state"],
        "switches": switches.as_dict(),
    }
    await publish_health(governor=governor, switches=switches, planner=summary)
    if decision.runs or reaped:
        logger.info("zoho.planner.tick", **summary)
    else:
        logger.debug("zoho.planner.tick", **summary)
    return summary


async def publish_health(*, governor: dict, switches: SwitchState, planner: dict) -> None:
    """Snapshot for /metrics and the operator API (never computed at scrape time)."""
    from app.modules.zoho.core.auth import zoho_token_manager

    token = await zoho_token_manager.health()
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "planner_last_tick": planner["at"],
        "planner": planner,
        "governor": governor,
        "switches": switches.as_dict(),
        "token": token,
    }
    try:
        await redis_client.set(HEALTH_KEY, json.dumps(payload, default=str), ex=600)
    except RedisError as exc:
        logger.warning("zoho.planner.health_publish_failed", error=str(exc))


__all__ = [
    "Continuation",
    "HEALTH_KEY",
    "LANE_MANUAL",
    "LANE_PRIORITY",
    "LANE_SCHEDULED",
    "LANE_WEEKLY_FULL",
    "ModuleView",
    "Plan",
    "PlannedRun",
    "Skip",
    "persist_quota_day",
    "plan",
    "publish_health",
    "registered_modules",
    "reseed_governor",
    "tick",
    "write_pressure",
]
