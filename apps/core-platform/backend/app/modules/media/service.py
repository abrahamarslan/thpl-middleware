"""Media orchestration: sanitise → store bytes → record the row → queue conversions.

The request only validates, writes the original and one row. Every variant is
generated later by Celery (queue ``documents``): CPU-bound Pillow work never
blocks the API event loop.

Replacing an image mints a NEW media row (new uuid, new storage keys) and
soft-deletes the old one; ``gc_deleted_media`` purges the old bytes after a
24 h grace window. Nothing is ever overwritten in place, which is what makes
the public URLs cache-safe forever.
"""

from __future__ import annotations

import asyncio
import uuid as uuid_mod

import structlog
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.modules.activity.recorder import record_activity
from app.modules.media.conversions import (
    AVATAR_COLLECTION,
    COLLECTION_DEFAULTS,
    USER_MODEL_TYPE,
    ConversionSpec,
)
from app.modules.media.imaging import InvalidImageError, sanitize_original
from app.modules.media.model import Media
from app.modules.media.repository import (
    create_media,
    get_active_media,
    list_active_media,
    soft_delete_media,
)
from app.modules.media.storage import default_disk, get_storage_provider, public_media_url

logger = structlog.get_logger("app.media")

ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class InvalidMediaError(AppError):
    status_code = 400
    code = "invalid_media"


def _dispatch_conversions(media_id: str, conversions: dict[str, ConversionSpec]) -> None:
    from app.tasks.media import dispatch_conversions  # lazy: the task module imports this package

    dispatch_conversions(media_id, conversions)


def media_urls(media: Media) -> dict[str, str | None]:
    """Public URL per variant; ``None`` for a variant that is not ready yet.

    ``original`` is always present (it is stored before the row is created).
    Private media has no public URLs at all.
    """
    if media.visibility != "public":
        return {}
    media_id = str(media.uuid)
    urls: dict[str, str | None] = {"original": public_media_url(media_id, "original")}
    for name in COLLECTION_DEFAULTS.get(media.collection, {}).get("conversions", {}):
        info = (media.conversions or {}).get(name) or {}
        urls[name] = public_media_url(media_id, name) if info.get("status") == "done" else None
    return urls


async def replace_image(
    db: AsyncSession,
    *,
    model_type: str,
    model_id: int,
    collection: str,
    upload: UploadFile,
    actor_id: int | None = None,
) -> Media:
    """Store ``upload`` as the owner's single image of ``collection``."""
    policy = COLLECTION_DEFAULTS[collection]
    visibility: str = policy["visibility"]
    conversions: dict[str, ConversionSpec] = policy["conversions"]

    if upload.content_type not in ALLOWED_MIME:
        raise InvalidMediaError("unsupported image type (allowed: PNG, JPEG, WebP)")
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)     # never buffer more than the cap
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidMediaError(f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    # Decode + validate + strip EXIF/GPS BEFORE anything is persisted or queued.
    # CPU-bound (a 40 MP decode is hundreds of ms), so off the event loop.
    try:
        image = await asyncio.to_thread(sanitize_original, raw)
    except InvalidImageError as e:
        raise InvalidMediaError(str(e)) from e

    media_id = uuid_mod.uuid4()
    key = f"{media_id}/original.{image.ext}"

    provider = get_storage_provider(default_disk())    # driver for NEW uploads only
    await provider.save(image.data, key, content_type=image.mime_type, visibility=visibility)

    try:
        previous = await list_active_media(db, model_type=model_type, model_id=model_id, collection=collection)
        media = await create_media(
            db,
            uuid=media_id, model_type=model_type, model_id=model_id, collection=collection,
            disk=provider.disk, visibility=visibility, file_name=key,
            mime_type=image.mime_type, size_bytes=len(image.data),
            status="pending" if conversions else "done",        # nothing to generate = already complete
            conversions={},
        )
        for old in previous:
            await soft_delete_media(db, old, reason="replaced")
        await record_activity(
            db, action="media_uploaded", actor_id=actor_id,
            subject_type=model_type, subject_id=model_id,
            changes={"media_id": str(media_id), "collection": collection, "replaced": [str(o.uuid) for o in previous]},
        )
        await db.commit()             # BEFORE dispatch: a worker must find the row
    except Exception:
        await db.rollback()
        try:                          # don't leave an orphan the row will never point at
            await provider.delete(key, visibility=visibility)
        except Exception:  # noqa: BLE001
            logger.warning("media_orphan_cleanup_failed", key=key, disk=provider.disk)
        raise

    try:
        await asyncio.to_thread(_dispatch_conversions, str(media_id), conversions)
    except Exception:  # noqa: BLE001 — the upload succeeded; a broker outage must not fail it
        logger.exception("media_dispatch_failed", media_id=str(media_id))
    else:
        logger.info("media_conversions_queued", media_id=str(media_id), conversions=list(conversions))
    return media


async def delete_image(
    db: AsyncSession, *, model_type: str, model_id: int, collection: str, actor_id: int | None = None,
) -> int:
    """Soft-delete the owner's live media in ``collection``. Returns how many."""
    rows = await list_active_media(db, model_type=model_type, model_id=model_id, collection=collection)
    for media in rows:
        await soft_delete_media(db, media, reason="deleted by owner")
    if rows:
        await record_activity(
            db, action="media_deleted", actor_id=actor_id, subject_type=model_type, subject_id=model_id,
            changes={"collection": collection, "media": [str(m.uuid) for m in rows]},
        )
    return len(rows)


# ── users' avatar (the first consumer; logo/selfie collections follow the same shape) ──

async def replace_avatar(db: AsyncSession, *, user_id: int, upload: UploadFile) -> Media:
    return await replace_image(
        db, model_type=USER_MODEL_TYPE, model_id=user_id, collection=AVATAR_COLLECTION,
        upload=upload, actor_id=user_id,
    )


async def delete_avatar(db: AsyncSession, *, user_id: int) -> int:
    return await delete_image(
        db, model_type=USER_MODEL_TYPE, model_id=user_id, collection=AVATAR_COLLECTION, actor_id=user_id,
    )


async def avatar_urls(db: AsyncSession, user_id: int) -> dict[str, str | None] | None:
    """Variant → URL for the user's live avatar; ``None`` when they have none."""
    media = await get_active_media(db, model_type=USER_MODEL_TYPE, model_id=user_id, collection=AVATAR_COLLECTION)
    return media_urls(media) if media is not None else None


async def avatar_urls_for_users(
    db: AsyncSession, user_ids: list[int],
) -> dict[int, dict[str, str | None]]:
    """Variant → URL per user, resolved in ONE query (no N+1 on list endpoints).

    Users without a live avatar are absent from the result; callers treat a
    missing id as ``None``. Newest media wins per user, the same rule as
    ``get_active_media`` (two concurrent uploads can briefly leave two live rows).
    """
    ids = set(user_ids)
    if not ids:
        return {}
    rows = (await db.execute(
        select(Media)
        .where(
            Media.model_type == USER_MODEL_TYPE,
            Media.collection == AVATAR_COLLECTION,
            Media.model_id.in_(ids),
        )
        .order_by(Media.model_id, Media.created_at.desc(), Media.id.desc())
    )).scalars().all()
    out: dict[int, dict[str, str | None]] = {}
    for media in rows:
        if media.model_id not in out:
            out[media.model_id] = media_urls(media)
    return out
