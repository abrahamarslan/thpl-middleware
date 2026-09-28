"""Async media queries (FastAPI layer). The Celery side is repository_worker.py."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.model import Media


async def create_media(db: AsyncSession, **fields) -> Media:
    media = Media(**fields)
    db.add(media)
    await db.flush()
    return media


async def get_media_by_uuid(db: AsyncSession, media_id: UUID, *, all_tenants: bool = False) -> Media | None:
    """One media row (soft-deleted rows are filtered out by the model's mixin).

    ``all_tenants`` is for the unauthenticated public router, which has no
    tenant context by design and must not depend on the default tenant.
    """
    stmt = select(Media).where(Media.uuid == media_id)
    if all_tenants:
        stmt = stmt.execution_options(all_tenants=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_active_media(db: AsyncSession, *, model_type: str, model_id: int, collection: str) -> list[Media]:
    """Live media of an owner's collection, newest first."""
    result = await db.execute(
        select(Media)
        .where(Media.model_type == model_type, Media.model_id == model_id, Media.collection == collection)
        .order_by(Media.created_at.desc(), Media.id.desc())
    )
    return list(result.scalars().all())


async def get_active_media(db: AsyncSession, *, model_type: str, model_id: int, collection: str) -> Media | None:
    """The newest live media of a single-valued collection (an avatar).

    Newest, not "the only one": two concurrent uploads can briefly leave two
    live rows, and the newest must win rather than raising MultipleResultsFound.
    """
    rows = await list_active_media(db, model_type=model_type, model_id=model_id, collection=collection)
    return rows[0] if rows else None


async def soft_delete_media(db: AsyncSession, media: Media, *, reason: str | None = None) -> None:
    """Soft delete only — bytes are purged by ``gc_deleted_media`` after the grace window."""
    media.soft_delete(reason=reason)
    await db.flush()
