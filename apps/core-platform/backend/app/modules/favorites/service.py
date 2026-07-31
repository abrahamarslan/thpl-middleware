"""Favorites module — business logic (add / remove / toggle / list)."""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.favorites import crud
from app.modules.favorites.model import Favorite
from app.modules.favorites.schema import FavoriteCreate, FavoriteListFilters

logger = structlog.get_logger("app.favorites")


async def list_favorites(db: AsyncSession, user_id: int, filters: FavoriteListFilters) -> tuple[list[Favorite], int]:
    return await crud.list_for_user(db, user_id, filters)


async def add_favorite(db: AsyncSession, user_id: int, body: FavoriteCreate, *, actor_label: str | None = None) -> Favorite:
    if await crud.get_target(db, user_id, body.favoritable_type, body.favoritable_id, body.collection_name):
        raise ConflictError("Already in favorites")
    fav = await crud.create(db, {"user_id": user_id, **body.model_dump()})
    logger.info("favorite_added", user_id=user_id, type=fav.favoritable_type, target=fav.favoritable_id)
    await record_activity(
        db, action="favorite.added", actor_id=user_id, actor_label=actor_label,
        subject_type=fav.favoritable_type, subject_id=fav.favoritable_id,
    )
    return fav


async def remove_favorite(db: AsyncSession, user_id: int, favorite_id: uuid.UUID, *, actor_label: str | None = None) -> None:
    fav = await crud.get_by_uuid(db, user_id, favorite_id)
    if fav is None:
        raise NotFoundError("Favorite not found")
    fav_type, fav_target = fav.favoritable_type, fav.favoritable_id
    await crud.delete(db, fav)
    logger.info("favorite_removed", user_id=user_id, type=fav_type, target=fav_target)
    await record_activity(
        db, action="favorite.removed", actor_id=user_id, actor_label=actor_label,
        subject_type=fav_type, subject_id=fav_target,
    )


async def toggle_favorite(db: AsyncSession, user_id: int, body: FavoriteCreate, *, actor_label: str | None = None) -> tuple[bool, Favorite | None]:
    """Idempotent switch: favorite if absent, remove if present.

    Returns (favorited_now, favorite_or_None).
    """
    existing = await crud.get_target(db, user_id, body.favoritable_type, body.favoritable_id, body.collection_name)
    if existing:
        await crud.delete(db, existing)
        await record_activity(
            db, action="favorite.removed", actor_id=user_id, actor_label=actor_label,
            subject_type=body.favoritable_type, subject_id=body.favoritable_id,
        )
        return False, None
    fav = await crud.create(db, {"user_id": user_id, **body.model_dump()})
    await record_activity(
        db, action="favorite.added", actor_id=user_id, actor_label=actor_label,
        subject_type=body.favoritable_type, subject_id=body.favoritable_id,
    )
    return True, fav
