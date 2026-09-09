"""Transport schemas for the media module."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    model_type: str
    model_id: str
    collection_name: str | None = None
    file_name: str
    original_name: str | None = None
    mime_type: str | None = None
    disk: str | None = None
    size: int | None = None
    conversions: dict | None = None
    custom_properties: dict | None = None
    order_column: int | None = None
    urls: dict[str, str]  # @property on the model — Pydantic reads it directly
    created_at: datetime
    updated_at: datetime
