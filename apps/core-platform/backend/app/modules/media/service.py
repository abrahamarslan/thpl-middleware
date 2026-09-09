"""Media orchestration: save bytes -> track row -> queue conversions.

The API request only writes bytes + one row; Pillow conversions happen in
the Celery ``documents`` queue (CPU-bound work never blocks the API loop).
Conversion specs come from the owning model's ``__media_conversions__`` or
are passed explicitly for detached uploads.
"""

import uuid as uuid_mod

import structlog
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.media.model import Media
from app.modules.media.storage import StorageProvider, get_storage

logger = structlog.get_logger("app.media")


async def attach_media(
    db: AsyncSession,
    *,
    model_type: str,
    model_id: str,
    file: UploadFile,
    collection: str = "default",
    conversions: dict[str, tuple[int, int]] | None = None,
    custom_properties: dict | None = None,
    actor_id: int | None = None,
    storage: StorageProvider | None = None,
) -> Media:
    storage = storage or get_storage()

    ext = (file.filename or "bin").rsplit(".", 1)[-1].lower()
    stored_name = f"{uuid_mod.uuid4().hex}.{ext}"

    content = await file.read()
    disk_used = await storage.save(content, stored_name)

    media = Media(
        model_type=model_type,
        model_id=str(model_id),
        collection_name=collection,
        file_name=stored_name,
        original_name=file.filename,
        mime_type=file.content_type,
        size=len(content),
        disk=disk_used,
        conversions={name: "pending" for name in (conversions or {})},
        custom_properties=custom_properties,
    )
    db.add(media)
    await db.flush()

    await record_activity(
        db, action="media_uploaded", actor_id=actor_id,
        subject_type=model_type, subject_id=model_id,
        changes={"media_id": media.id, "file": file.filename, "collection": collection},
    )

    if conversions:
        from app.tasks.media import generate_conversions  # lazy: avoid task import cycle

        generate_conversions.apply_async(
            kwargs={"media_id": media.id, "conversions": {k: list(v) for k, v in conversions.items()}},
            countdown=2,  # let the caller's transaction commit first
        )
        logger.info("media_conversions_queued", media_id=media.id, conversions=list(conversions))

    return media


async def list_media_for_entity(
    db: AsyncSession, model_type: str, model_id: str, collection: str | None = None
) -> list[Media]:
    stmt = select(Media).where(Media.model_type == model_type, Media.model_id == str(model_id))
    if collection:
        stmt = stmt.where(Media.collection_name == collection)
    stmt = stmt.order_by(Media.order_column.asc(), Media.id.asc())
    return list((await db.scalars(stmt)).all())


async def delete_media(db: AsyncSession, media_id: int, *, actor_id: int | None = None) -> None:
    media = await db.get(Media, media_id)
    if media is None:
        raise NotFoundError("Media not found")
    media.soft_delete()  # bytes stay on disk; a maintenance sweep can purge later
    await db.flush()
    await record_activity(
        db, action="media_deleted", actor_id=actor_id,
        subject_type=media.model_type, subject_id=media.model_id,
        changes={"media_id": media_id},
    )
