"""Media conversion tasks (queue: documents — CPU-bound, like PDF work).

Pillow resizing is synchronous CPU work, so it runs directly in the worker;
only the DB status update uses the async _run pattern (asyncpg-only stack).
"""

import asyncio
from pathlib import Path

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.conf import settings

logger = structlog.get_logger("app.tasks.media")


def _resize(source: Path, conversions: dict[str, list[int]]) -> dict[str, str]:
    """Produce ``<name>-<conv>.<ext>`` siblings; returns per-conversion status."""
    from PIL import Image

    results: dict[str, str] = {}
    base_name, _, ext = source.name.rpartition(".")
    with Image.open(source) as img:
        for conv_name, (width, height) in conversions.items():
            try:
                variant = img.copy()
                variant.thumbnail((width, height))
                variant.save(source.with_name(f"{base_name}-{conv_name}.{ext}"))
                results[conv_name] = "done"
            except Exception as e:  # noqa: BLE001 — one bad conversion isn't fatal
                logger.error("media_conversion_failed", file=source.name, conversion=conv_name, error=str(e))
                results[conv_name] = "failed"
    return results


@shared_task(bind=True, name="app.tasks.media.generate_conversions", max_retries=3, retry_backoff=30)
def generate_conversions(self, media_id: int, conversions: dict[str, list[int]]) -> dict:
    from app.modules.media.model import Media
    from app.modules.media.storage import get_storage

    async def work() -> dict:
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as db:
                media = await db.get(Media, media_id, execution_options={"include_deleted": True})
                if media is None:
                    return {"status": "missing"}

                storage = get_storage()
                source = storage.local_path(media.file_name)
                if source is None or not source.exists():
                    logger.warning("media_source_unavailable", media_id=media_id, disk=media.disk)
                    media.conversions = {**(media.conversions or {}), **{c: "skipped" for c in conversions}}
                    await db.commit()
                    return {"status": "skipped", "reason": "source_not_local"}

                results = await asyncio.to_thread(_resize, source, conversions)
                media.conversions = {**(media.conversions or {}), **results}
                await db.commit()
                return {"status": "ok", "results": results}
        finally:
            await engine.dispose()

    out = asyncio.run(work())
    if out.get("status") == "missing":
        # Enqueued before the upload transaction committed — retry shortly.
        raise self.retry(countdown=10)
    logger.info("media_conversions_complete", media_id=media_id, **out)
    return out
