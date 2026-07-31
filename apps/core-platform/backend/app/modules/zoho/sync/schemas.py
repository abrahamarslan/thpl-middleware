"""Transport schemas for the sync-engine admin API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SyncStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    module_name: str
    last_sync_time: datetime | None = None
    last_full_sync_time: datetime | None = None
    last_incremental_cursor: str | None = None
    last_zoho_id_synced: str | None = None
    total_records_synced: int | None = None
    records_created: int | None = None
    records_updated: int | None = None
    skipped_records: int | None = None
    error_count: int | None = None
    run_count: int | None = None
    last_run_status: str | None = None
    last_run_mode: str | None = None
    last_run_duration_ms: int | None = None
    last_error: str | None = None


class ModuleInfoOut(BaseModel):
    """One registered sync module: effective config summary + live stats."""

    module: str
    endpoint: str
    strategy: str
    direction: str
    detail_required: bool
    detail_dispatch: str
    batch_size: int
    sync_interval_minutes: int
    enabled: bool
    field_count: int
    nested_modules: list[str]
    stats: SyncStatOut | None = None


class QueueLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module_name: str
    zoho_id: str | None = None
    local_id: str | None = None
    operation: str
    status: str
    attempt: int | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    celery_task_id: str | None = None
    request_id: str | None = None
    error: str | None = None


class SyncRunAccepted(BaseModel):
    module: str
    mode: str
    task_id: str
