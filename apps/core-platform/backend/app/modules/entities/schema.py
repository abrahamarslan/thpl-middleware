"""Transport schemas for the ``core`` entity registry and aliases."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field

from app.modules.entities.enums import EntityAliasKind


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EntityTypeOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    target_schema: str
    target_table: str
    description: str | None = None


class EntityAliasCreate(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    entity_id: int = Field(..., ge=1)
    alias: str = Field(..., min_length=1, max_length=500)
    kind: EntityAliasKind | None = None
    language_code: str | None = Field(None, max_length=16)


class EntityAliasOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    entity_type: str
    entity_id: int
    alias: str
    alias_normalized: str | None = None
    kind: str | None = None
    language_code: str | None = None
    created_at: dt.datetime


__all__ = ["EntityAliasCreate", "EntityAliasOut", "EntityTypeOut"]
