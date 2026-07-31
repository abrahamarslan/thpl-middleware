"""Activity module — transport schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    activity_id: uuid.UUID
    action: str
    status: str
    description: str | None = None
    actor_id: int | None = None
    actor_type: str
    actor_label: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    changes: dict | None = None
    context: dict | None = None
    request_id: str | None = None
    ip_address: str | None = None
    tenant_id: uuid.UUID | None = None
    created_at: datetime


class ActivityListFilters(BaseModel):
    action: str | None = None
    actor_id: int | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    status: str | None = None
    since: datetime | None = Field(default=None, description="created_at >= since")
    until: datetime | None = Field(default=None, description="created_at <= until")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
