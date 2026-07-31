"""Favorites module — HTTP endpoints. All scoped to the current user."""

import uuid

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.favorites import service
from app.modules.favorites.schema import (
    FavoriteCreate,
    FavoriteListFilters,
    FavoriteOut,
    FavoriteToggleResult,
)
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[PageModel[FavoriteOut]])
async def list_favorites(db: DBSession, current: CurrentUser, filters: FavoriteListFilters = Query()):
    rows, total = await service.list_favorites(db, current.id, filters)
    return ResponseModel(
        data=PageModel(
            items=[FavoriteOut.model_validate(r) for r in rows],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@router.post("", response_model=ResponseModel[FavoriteOut], status_code=201)
async def add_favorite(db: DBSession, current: CurrentUser, body: FavoriteCreate):
    fav = await service.add_favorite(db, current.id, body, actor_label=current.email)
    return ResponseModel(data=FavoriteOut.model_validate(fav))


@router.post("/toggle", response_model=ResponseModel[FavoriteToggleResult])
async def toggle_favorite(db: DBSession, current: CurrentUser, body: FavoriteCreate):
    favorited, fav = await service.toggle_favorite(db, current.id, body, actor_label=current.email)
    return ResponseModel(
        data=FavoriteToggleResult(
            favorited=favorited,
            favorite=FavoriteOut.model_validate(fav) if fav else None,
        )
    )


@router.delete("/{favorite_id}", response_model=ResponseModel[dict])
async def remove_favorite(db: DBSession, current: CurrentUser, favorite_id: uuid.UUID):
    await service.remove_favorite(db, current.id, favorite_id, actor_label=current.email)
    return ResponseModel(data={"removed": True})
