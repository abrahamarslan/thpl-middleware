"""Favorites module — async data access."""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.favorites.model import Favorite
from app.modules.favorites.schema import FavoriteListFilters


async def get_by_uuid(db: AsyncSession, user_id: int, favorite_id: uuid.UUID) -> Favorite | None:
    return await db.scalar(
        select(Favorite).where(Favorite.favorite_id == favorite_id, Favorite.user_id == user_id)
    )


async def get_target(
    db: AsyncSession, user_id: int, favoritable_type: str, favoritable_id: str,
    collection_name: str = "default",
) -> Favorite | None:
    return await db.scalar(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.favoritable_type == favoritable_type,
            Favorite.favoritable_id == favoritable_id,
            Favorite.collection_name == collection_name,
        )
    )


async def list_for_user(db: AsyncSession, user_id: int, f: FavoriteListFilters) -> tuple[list[Favorite], int]:
    query: Select = select(Favorite).where(Favorite.user_id == user_id)
    if f.favoritable_type:
        query = query.where(Favorite.favoritable_type == f.favoritable_type)
    if f.collection_name:
        query = query.where(Favorite.collection_name == f.collection_name)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(Favorite.position.asc(), Favorite.created_at.desc())
    query = query.offset((f.page - 1) * f.page_size).limit(f.page_size)
    rows = (await db.scalars(query)).all()
    return list(rows), total


async def create(db: AsyncSession, values: dict) -> Favorite:
    row = Favorite(**values)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, favorite: Favorite) -> None:
    await db.delete(favorite)
    await db.flush()
