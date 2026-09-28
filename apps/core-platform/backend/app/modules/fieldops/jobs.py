"""Deferred work after a request: metrics, dwell detection, checkpoint geocoding.

Enqueued BY NAME (``send_task``) so this module never imports the Celery task modules, with a
countdown so the request's transaction has committed before the task reads — and every task
is idempotent, so running early (it then finds nothing new) or twice is harmless. A broker
outage never fails the request: the periodic sweeps (``fieldops.recompute_stale_metrics``)
catch up on anything a lost enqueue missed.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger("app.fieldops.jobs")

COMPUTE_METRICS = "app.tasks.fieldops.compute_metrics"
DETECT_DWELL = "app.tasks.fieldops.detect_dwell"
GEOCODE_CHECKPOINTS = "app.tasks.fieldops.geocode_checkpoints"


def enqueue(task_name: str, *args, countdown: int = 5) -> None:
    try:
        from app.tasks.celery_app import celery_app

        celery_app.send_task(task_name, args=list(args), countdown=countdown, retry=False)
    except Exception as exc:  # noqa: BLE001 — deferred work must never fail the request
        logger.warning("fieldops.jobs.enqueue_failed", task=task_name, error=str(exc)[:200])


__all__ = ["COMPUTE_METRICS", "DETECT_DWELL", "GEOCODE_CHECKPOINTS", "enqueue"]
