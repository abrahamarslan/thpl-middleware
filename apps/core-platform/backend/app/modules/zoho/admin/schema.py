"""Operator API schemas (Slim for lists, Fat for detail)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SwitchUpdate(BaseModel):
    value: bool | list[str]
    reason: str = Field(min_length=3, max_length=500, description="Why — recorded in the audit log")


class ModulePauseRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RunRequest(BaseModel):
    mode: str | None = Field(default=None, pattern="^(full|incremental|index)$")
    reason: str | None = Field(default=None, max_length=500)


class RunSlimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    module: str
    lane: str
    mode: str | None = None
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    listed: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    stop_reason: str | None = None
    next_page: int | None = None
    error_category: str | None = None


class RunOut(RunSlimOut):
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    pages: int = 0
    resurrected: int = 0
    stale_ignored: int = 0
    skipped: int = 0
    soft_deleted: int = 0
    queued_details: int = 0
    details_saved: int = 0
    start_page: int | None = None
    error_fingerprint: str | None = None
    error_message: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    requested_by: int | None = None


class SyncEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    module: str
    local_id: int | None = None
    zoho_id: str | None = None
    event_type: str
    direction: str
    source: str | None = None
    run_id: uuid.UUID | None = None
    changed_fields: list[str] | None = None
    diff: dict[str, Any] | None = None
    zoho_last_modified_time: datetime | None = None
    actor_user_id: int | None = None
    request_id: str | None = None
    error_category: str | None = None
    message: str | None = None


class RetentionPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    module: str
    event_class: str
    keep_days: int
    archive: str
    enabled: bool
    updated_at: datetime | None = None


class RetentionPolicyUpdate(BaseModel):
    keep_days: int = Field(ge=1, le=3650)
    enabled: bool = True
    reason: str = Field(min_length=3, max_length=500)


class HealthOut(BaseModel):
    """Everything an operator needs on one screen."""

    governor: dict[str, Any]
    switches: dict[str, Any]
    token: dict[str, Any]
    breakers: list[dict[str, Any]]
    planner: dict[str, Any] | None = None
    running_runs: int


class ConfigUpdate(BaseModel):
    value: Any = Field(description="New value; type and bounds depend on the knob")
    reason: str = Field(min_length=3, max_length=500)
