"""Favorites module — transport schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FavoriteTarget(BaseModel):
    """Identifies the thing being favorited."""

    favoritable_type: str = Field(description="e.g. 'file', 'zoho_item', 'user'")
    favoritable_id: str


class FavoriteCreate(FavoriteTarget):
    collection_name: str = Field(default="default", description="Grouping, e.g. 'Wishlist'")
    label: str | None = None
    note: str | None = None
    position: int = 0


class FavoriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    favorite_id: uuid.UUID
    user_id: int
    favoritable_type: str
    favoritable_id: str
    collection_name: str = "default"
    label: str | None = None
    note: str | None = None
    position: int
    created_at: datetime


class FavoriteToggleResult(BaseModel):
    favorited: bool = Field(description="True if now favorited, False if removed")
    favorite: FavoriteOut | None = None


class FavoriteListFilters(BaseModel):
    favoritable_type: str | None = None
    collection_name: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
