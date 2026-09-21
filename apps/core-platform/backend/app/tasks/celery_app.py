"""Celery application.

Topology (all defined in docker-compose):
  celery-worker  — consumes queues: default, integrations, documents
  celery-beat    — cron-style scheduler (replaces APScheduler entirely)
  flower         — task dashboard at https://<domain>/flower (basic-auth)
  celery-exporter— Prometheus metrics (task rates, latency, failures)

Queues:
  default       — misc app tasks
  integrations  — Zoho syncs (rate-limit-sensitive, retried with backoff)
  documents     — Typst PDF rendering (slow, CPU-bound)

Scaling rule: one worker container per queue class once load grows, e.g.
  celery -A app.tasks.celery_app worker -Q documents -c 2

Async tasks: every worker process owns ONE event loop (app/tasks/_loop.py,
ADR‑3) — run the prefork pool (the default). ``-P threads`` / ``gevent``
would share a loop between concurrent tasks and is not supported.
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_process_init, worker_process_shutdown

from app.core.conf import settings

celery_app = Celery(
    "core_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.zoho_sync",
        "app.tasks.documents",
        "app.tasks.emails",
        "app.tasks.media",
        "app.tasks.maintenance",
        "app.tasks.authentik",
    ],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    # Reliability
    task_acks_late=True,                  # re-deliver if a worker dies mid-task
    worker_prefetch_multiplier=1,         # fair dispatch for long tasks
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=86400,
    # Routing
    task_default_queue="default",
    task_routes={
        "app.tasks.zoho_sync.*": {"queue": "integrations"},
        "app.tasks.emails.*": {"queue": "integrations"},
        "app.tasks.documents.*": {"queue": "documents"},
        "app.tasks.media.*": {"queue": "documents"},
    },
    # Events — required by Flower and celery-exporter
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Periodic schedule (Celery Beat)
    beat_schedule={
        # NOTE: `zoho-sync-items` (*/15) and `zoho-sync-contacts` (2 h) were
        # REMOVED on 2026-09-18 together with app/tasks/zoho.py. They paginated
        # whole catalogues only to log a row count — at 5k items that is ~1,700
        # wasted Zoho calls a day against a 45,000/day contract, with no data
        # written. See docs/zoho-sync-implementation/README.md (Phase 1).
        "cleanup-old-media": {
            "task": "app.tasks.maintenance.cleanup_old_media",
            "schedule": crontab(minute="30", hour="3"),
        },
        # The Zoho planner is the ONLY Zoho scheduler. It replaced
        # `zoho-sync-dispatcher` (every 5 min, no running guard → overlapping
        # runs) and `zoho-full-sync-weekly` (every module forced to a full scan
        # at the same instant). Each module's interval and the weekly full slot
        # are planner lanes; exclusion is a DB lease, not a schedule.
        # docs/zoho-sync-implementation/control-plane.md
        "zoho-planner": {
            "task": "app.tasks.zoho_sync.planner_tick",
            "schedule": 60.0,
            "options": {"expires": 55},          # a late tick is useless; never pile up
        },
        # Nightly: sync-event partitions ahead, expired partitions dropped,
        # retention policies applied. 21:15 UTC = 02:45 IST (quiet hours).
        "zoho-retention": {
            "task": "app.tasks.zoho_sync.retention_maintenance",
            "schedule": crontab(minute="15", hour="21"),
        },
        # Daily: verified documents past their expiry_date become `expired`
        # (docs/documents/README.md). 21:30 UTC = 03:00 IST.
        "documents-expiry": {
            "task": "app.tasks.documents.expire_due_documents",
            "schedule": crontab(minute="30", hour="21"),
        },
    },
)


@setup_logging.connect
def _setup_celery_logging(**_kwargs) -> None:
    """Same structlog JSON config as the API — one log format in Loki."""
    from app.common.log import configure_logging

    configure_logging()


@worker_process_init.connect
def _init_worker_otel(**_kwargs) -> None:
    from app.core.observability import setup_otel_celery

    setup_otel_celery()


@worker_process_init.connect
def _init_worker_loop(**_kwargs) -> None:
    """Fresh event loop per forked child; drop inherited pool state (ADR‑3)."""
    from app.tasks._loop import reset_after_fork

    reset_after_fork()


@worker_process_shutdown.connect
def _shutdown_worker_loop(**_kwargs) -> None:
    from app.tasks._loop import shutdown

    shutdown()
