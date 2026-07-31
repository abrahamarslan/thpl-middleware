"""Celery application.

Topology (all defined in docker-compose):
  celery-worker  — consumes queues: default, integrations, documents
  celery-beat    — cron-style scheduler (replaces APScheduler entirely)
  flower         — task dashboard at https://<domain>/flower (basic-auth)
  celery-exporter— Prometheus metrics (task rates, latency, failures)

Queues:
  default       — misc app tasks
  integrations  — Zoho syncs (rate-limit-sensitive, retried with backoff)
  documents     — Gotenberg PDF rendering (slow, CPU-bound)

Scaling rule: one worker container per queue class once load grows, e.g.
  celery -A app.tasks.celery_app worker -Q documents -c 2
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_process_init

from app.core.conf import settings

celery_app = Celery(
    "core_platform",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.zoho",
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
        "app.tasks.zoho.*": {"queue": "integrations"},
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
        "zoho-sync-items": {
            "task": "app.tasks.zoho.sync_items",
            "schedule": crontab(minute="*/15"),
        },
        "zoho-sync-contacts": {
            "task": "app.tasks.zoho.sync_contacts",
            "schedule": crontab(minute="5", hour="*/2"),
        },
        "cleanup-old-media": {
            "task": "app.tasks.maintenance.cleanup_old_media",
            "schedule": crontab(minute="30", hour="3"),
        },
        # Sync-engine dispatcher: config-driven — every 5 min it enqueues an
        # incremental run for each registered module whose
        # sync_interval_minutes elapsed (no per-module beat entries needed).
        "zoho-sync-dispatcher": {
            "task": "app.tasks.zoho_sync.sync_all_due",
            "schedule": crontab(minute="*/5"),
        },
        # Weekly full-sync safety net for every registered module (catches
        # records that incremental windows can miss: merges, hard deletes).
        "zoho-full-sync-weekly": {
            "task": "app.tasks.zoho_sync.sync_all_due",
            "schedule": crontab(minute="0", hour="3", day_of_week="sunday"),
            "kwargs": {"force_mode": "full", "force": True},
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
