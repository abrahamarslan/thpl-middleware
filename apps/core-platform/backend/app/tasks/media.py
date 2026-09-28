"""Media conversion pipeline (queue: documents — CPU-bound, like PDF work).

Uses the SYNCHRONOUS storage clients exclusively (see storage_sync.py). Each
variant is its own chord subtask — independently retryable, and a failure in
one never blocks or corrupts the others — and ``finalize_conversions`` joins
them into the row's overall status.

A chord callback only fires when EVERY header task returns normally, so
``gen_variant`` never lets its final failure escape: after the last retry it
records the failure on the row and RETURNS ``status="failed"``. Raising there
would make Celery abort the chord and leave the row stuck in ``processing``.
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from celery import chord, shared_task

from app.modules.media.conversions import COLLECTION_DEFAULTS, ConversionSpec
from app.modules.media.imaging import InvalidImageError, mime_for_format, render_variant
from app.modules.media.repository_worker import media_repo_worker
from app.modules.media.storage_sync import get_storage_provider_sync

logger = structlog.get_logger("app.tasks.media")

GC_GRACE = timedelta(hours=24)
GC_BATCH = 200
#: A row idle this long in pending/processing is presumed orphaned by a crash.
#: Comfortably above one variant's runtime and the longest retry backoff step.
STUCK_IDLE = timedelta(minutes=15)
STUCK_BATCH = 100


def _record_failure(media_id: str, variant_name: str, error: str) -> dict:
    media_repo_worker.set_conversion(media_id, variant_name, {"status": "failed", "error": error[:500]})
    return {"variant": variant_name, "status": "failed", "error": error[:500]}


@shared_task(bind=True, name="app.tasks.media.gen_variant", max_retries=3, queue="documents")
def gen_variant(self, media_id: str, variant_name: str, spec: ConversionSpec) -> dict:
    """Generate ONE conversion variant.

    Idempotent: a retry, or a redelivery after a worker crash, safely overwrites
    whatever partial output the previous attempt produced (same key, same bytes).
    """
    media = media_repo_worker.get(media_id)
    if media is None:
        return {"variant": variant_name, "status": "skipped", "reason": "media deleted"}

    media_repo_worker.mark_processing(media_id)
    try:
        provider = get_storage_provider_sync(media["disk"])
        source_bytes = provider.read(media["file_name"], visibility=media["visibility"])
        variant_bytes, width, height = render_variant(source_bytes, spec)

        ext = spec.get("format", "webp")
        key = f"{media_id}/{variant_name}.{ext}"
        provider.save(variant_bytes, key, content_type=mime_for_format(ext), visibility=media["visibility"])

        media_repo_worker.set_conversion(
            media_id, variant_name,
            {"status": "done", "file_name": key, "w": width, "h": height, "size": len(variant_bytes)},
        )
        return {"variant": variant_name, "status": "done"}

    except (InvalidImageError, ValueError, KeyError) as exc:
        # Retrying cannot fix an undecodable source or a bad spec.
        logger.warning("media_variant_rejected", media_id=media_id, variant=variant_name, error=str(exc))
        return _record_failure(media_id, variant_name, str(exc))

    except Exception as exc:  # noqa: BLE001 — storage/DB hiccups are worth retrying
        if self.request.retries >= self.max_retries:
            logger.error("media_variant_failed", media_id=media_id, variant=variant_name, error=str(exc))
            return _record_failure(media_id, variant_name, str(exc))
        raise self.retry(exc=exc, countdown=30 * 2 ** self.request.retries) from exc


@shared_task(name="app.tasks.media.finalize_conversions", queue="documents")
def finalize_conversions(results: list[dict], media_id: str) -> None:
    """Chord callback — runs once every ``gen_variant`` subtask has returned."""
    statuses = {r["variant"]: r["status"] for r in results if r}
    if statuses and all(s == "skipped" for s in statuses.values()):
        return                                  # the media was deleted meanwhile — nothing to record
    overall = "done" if all(s in ("done", "skipped") for s in statuses.values()) else "partial_failure"
    media_repo_worker.set_status(media_id, overall)
    logger.info("media_conversions_finalized", media_id=media_id, status=overall, variants=statuses)


def dispatch_conversions(media_id: str, conversions: dict[str, ConversionSpec]) -> None:
    """Queue every variant as a chord. Call it AFTER the row's transaction has
    committed — a worker that starts first would find no row and skip."""
    if not conversions:
        return
    header = [gen_variant.s(media_id, name, spec) for name, spec in conversions.items()]
    chord(header)(finalize_conversions.s(media_id=media_id))


@shared_task(name="app.tasks.media.requeue_stuck_media", queue="documents")
def requeue_stuck_media() -> dict:
    """Celery beat, every 10 min. Rescue rows a crash left half-done.

    ``gen_variant`` never lets a failure escape, but nothing a task does can help
    when the WORKER dies mid-chord (OOM, deploy, lost broker) or the broker was
    down when the upload dispatched: the row would sit in ``pending`` /
    ``processing`` forever. Variants are idempotent, so the rescue is simple —
    re-dispatch only the variants that are not ``done``.

    Rows past ``STUCK_GIVE_UP_AFTER`` are marked ``partial_failure`` instead of
    being retried indefinitely.
    """
    requeued = finished = gave_up = 0
    for row in media_repo_worker.list_stuck(STUCK_IDLE, limit=STUCK_BATCH):
        media_id = row["uuid"]
        specs = COLLECTION_DEFAULTS.get(row["collection"], {}).get("conversions", {})
        current = row["conversions"] or {}
        missing = {n: s for n, s in specs.items() if current.get(n, {}).get("status") != "done"}
        if not missing:                       # nothing (left) to generate: it was only the status that never landed
            media_repo_worker.set_status(media_id, "done")
            finished += 1
        elif row["too_old"]:
            media_repo_worker.set_status(media_id, "partial_failure")
            logger.error("media_gave_up", media_id=media_id, missing=list(missing))
            gave_up += 1
        else:
            media_repo_worker.touch(media_id)
            dispatch_conversions(media_id, missing)
            logger.warning("media_requeued", media_id=media_id, variants=list(missing))
            requeued += 1
    return {"requeued": requeued, "finished": finished, "gave_up": gave_up}


@shared_task(name="app.tasks.media.gc_deleted_media", queue="documents")
def gc_deleted_media() -> dict:
    """Celery beat, every 15 min. Purge media soft-deleted more than 24h ago.

    The grace window exists because public URLs are content-addressed and may
    still be cached at an edge/CDN or held by another application: deleting the
    bytes the moment an avatar is replaced could break a page load in flight
    elsewhere.
    """
    purged = failed = 0
    for media in media_repo_worker.list_stale_deleted(GC_GRACE, limit=GC_BATCH):
        try:
            provider = get_storage_provider_sync(media["disk"])
            keys = [media["file_name"]] + [
                c["file_name"] for c in (media["conversions"] or {}).values() if c.get("file_name")
            ]
            for key in keys:
                provider.delete(key, visibility=media["visibility"])
            media_repo_worker.hard_delete(media["id"])
            purged += 1
        except Exception as exc:  # noqa: BLE001 — one unreachable disk must not stall the whole sweep
            failed += 1
            logger.error("media_gc_failed", media_id=media["uuid"], disk=media["disk"], error=str(exc))
    if purged or failed:
        logger.info("media_gc_complete", purged=purged, failed=failed)
    return {"purged": purged, "failed": failed}
