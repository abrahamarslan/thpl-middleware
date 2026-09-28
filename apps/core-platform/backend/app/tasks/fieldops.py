"""Field-operations background work (docs/fieldops/implementation-of-shift-visits-system.md §15).

Every task: runs its async body on the worker's loop (``_loop.run_async``, ADR-3), in system
scope as ``system:fieldops-<task>`` (no RBAC evaluation — trusted code), commits its own
session, and is IDEMPOTENT — a retried or duplicated message changes nothing twice.

Periodic (beat, ``celery_app.py``)::

    fieldops-auto-close          5 min   close shifts past their cap (ghost / auto-closed anomalies)
    fieldops-link-orphan-pings  10 min   back-fill shift_id / visit_id of fixes that beat their entity
    fieldops-recompute-metrics  15 min   closed shifts without (fresh) metrics — catches lost enqueues
    fieldops-geocode-checkpoints 10 min  address labels for new checkpoints (only when geocoding is on)
    fieldops-mark-missed        hourly   planned visits whose window passed → missed
    fieldops-maintenance        daily    stream partitions ahead, retention, idempotency-key purge

On demand (enqueued by name from ``app/modules/fieldops/jobs.py``): ``compute_metrics``,
``detect_dwell``.
"""

from __future__ import annotations

import datetime as dt

import structlog
from celery import shared_task

logger = structlog.get_logger("app.tasks.fieldops")


def _run(component: str, body):
    """Run ``body(db)`` in system scope on the worker loop; commit; return its result."""
    from app.database.db import async_session_factory
    from app.modules.rbac.context import system_scope
    from app.tasks._loop import run_async

    async def work():
        with system_scope(f"fieldops-{component}"):
            async with async_session_factory() as db:
                result = await body(db)
                await db.commit()
                return result

    return run_async(work())


@shared_task(name="app.tasks.fieldops.auto_close_shifts")
def auto_close_shifts() -> dict:
    from app.modules.fieldops.service import metrics, shifts

    async def body(db):
        closed = await shifts.auto_close_due(db)
        for shift_id in closed:
            await metrics.compute_shift_metrics(db, shift_id)
        return {"closed": len(closed)}

    result = _run("autoclose", body)
    if result["closed"]:
        logger.info("fieldops.auto_close", **result)
    return result


@shared_task(name="app.tasks.fieldops.link_orphan_pings")
def link_orphan_pings() -> dict:
    from app.modules.fieldops.service import ingest

    async def body(db):
        return {"linked": await ingest.link_orphan_pings(db)}

    return _run("linker", body)


@shared_task(name="app.tasks.fieldops.compute_metrics")
def compute_metrics(shift_id: int) -> dict:
    from app.modules.fieldops.service import metrics

    async def body(db):
        row = await metrics.compute_shift_metrics(db, shift_id)
        return {"shift_id": shift_id, "computed": row is not None}

    return _run("metrics", body)


@shared_task(name="app.tasks.fieldops.recompute_stale_metrics")
def recompute_stale_metrics() -> dict:
    from app.modules.fieldops.service import metrics

    async def body(db):
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=7)
        ids = await metrics.shifts_needing_metrics(db, since=since)
        for shift_id in ids:
            await metrics.compute_shift_metrics(db, shift_id)
        return {"recomputed": len(ids)}

    return _run("metrics", body)


@shared_task(name="app.tasks.fieldops.detect_dwell")
def detect_dwell(visit_id: int) -> dict:
    from sqlalchemy import select

    from app.modules.fieldops.model import Shift, Visit
    from app.modules.fieldops.service import verify
    from app.modules.fieldops.service.policy import EffectivePolicy

    async def body(db):
        visit = await db.scalar(select(Visit).where(Visit.id == visit_id))
        if visit is None:
            return {"visit_id": visit_id, "changed": False}
        shift = await db.get(Shift, visit.shift_id) if visit.shift_id else None
        policy = EffectivePolicy.from_snapshot(shift.policy_snapshot if shift else None)
        return {"visit_id": visit_id, "changed": await verify.detect_dwell(db, visit, policy)}

    return _run("dwell", body)


@shared_task(name="app.tasks.fieldops.geocode_checkpoints")
def geocode_checkpoints(limit: int = 200) -> dict:
    """Reverse-geocode new checkpoint fixes into ``address_label`` — checkpoints only, never the
    continuous stream, and through the geocoding service (cache, licence expiry, breaker, cost)."""
    from app.core.conf import settings

    if not getattr(settings, "GEOCODING_ENABLED", False):
        return {"skipped": "geocoding_disabled"}
    from app.modules.fieldops.service.geocode import label_checkpoints

    return _run("geocoder", lambda db: label_checkpoints(db, limit=limit))


@shared_task(name="app.tasks.fieldops.mark_missed_visits")
def mark_missed_visits() -> dict:
    from app.modules.fieldops.service.visits import mark_missed

    async def body(db):
        return {"missed": await mark_missed(db)}

    return _run("planner", body)


@shared_task(name="app.tasks.fieldops.maintenance")
def maintenance() -> dict:
    """Partitions ahead, retention (only when the DPDP rule enables auto-purge), idempotency purge."""
    from app.modules.fieldops import partitions
    from app.modules.idempotency.service import purge_expired

    async def body(db):
        created = await partitions.ensure_partitions(db)
        retention = await partitions.apply_retention(db)
        purged = await purge_expired(db)
        return {"partitions_created": created, "retention": retention, "idempotency_keys_purged": purged}

    result = _run("maintenance", body)
    logger.info("fieldops.maintenance", **{k: v for k, v in result.items() if k != "retention"},
                retention=result["retention"])
    return result
