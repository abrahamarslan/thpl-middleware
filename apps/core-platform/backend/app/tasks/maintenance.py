"""Housekeeping tasks (queue: default)."""

import time
from pathlib import Path

import structlog
from celery import shared_task

from app.core.conf import settings

logger = structlog.get_logger("app.tasks.maintenance")

_MAX_AGE_DAYS = 14


@shared_task(name="app.tasks.maintenance.cleanup_old_media")
def cleanup_old_media() -> dict:
    """Delete generated PDFs older than _MAX_AGE_DAYS from the media volume."""
    media = Path(settings.MEDIA_DIR)
    if not media.exists():
        return {"deleted": 0}

    cutoff = time.time() - _MAX_AGE_DAYS * 86400
    deleted = 0
    for f in media.rglob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            deleted += 1
    logger.info("media_cleanup_complete", deleted=deleted)
    return {"deleted": deleted}
