"""Transport schemas for the comments module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    owner_type: str = Field(..., description="core.entity_types.code of the owner, e.g. 'vehicle'")
    owner_id: int = Field(..., gt=0)
    body: str | None = None
    comment_type: str | None = None
    commented_at: datetime | None = Field(None, description="Defaults to now — set explicitly only when backfilling")


class CommentUpdate(BaseModel):
    body: str | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_type: str
    owner_id: int
    body: str | None
    comment_type: str | None
    operation_type: str | None
    is_system_generated: bool | None
    commented_by_user_id: int | None
    commented_by_name: str | None
    commented_by_external_id: str | None
    commented_at: datetime
    zoho_id: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["CommentCreate", "CommentOut", "CommentUpdate"]
