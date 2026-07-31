"""Transport schemas for the tags module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TagBase(BaseModel):
    name: dict[str, str] = Field(..., description='Locale map, e.g. {"en": "Urgent"}')
    slug: dict[str, str] = Field(..., description='Locale map, e.g. {"en": "urgent"}')
    type: str | None = None
    order_column: int | None = 0


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: dict[str, str] | None = None
    slug: dict[str, str] | None = None
    type: str | None = None
    order_column: int | None = None


class TagOut(TagBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class SyncTagsRequest(BaseModel):
    """Replace the full tag set of one entity (idempotent)."""

    taggable_id: str
    taggable_type: str
    tag_ids: list[int] = Field(default_factory=list)
