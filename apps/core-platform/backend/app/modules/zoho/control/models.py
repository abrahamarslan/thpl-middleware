"""Control-plane tables: runs, cursors, quota days, sync events, retention.

Doctrine (docs/zoho-sync-implementation/control-plane.md):
  * **Postgres is the source of truth for anything that must survive a
    crash** — who is running what (leases), where a scan resumes (cursors),
    how much quota a day used, and what happened to every record. Redis holds
    only what can be lost.
  * Run exclusion is enforced by the database (partial unique index on
    ``status='running'``), not by a TTL lock that can expire mid-run.
  * ``zoho_sync_events`` is append-only and partitioned by day so retention is
    a partition drop, not a table-wide DELETE.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, LedgerMixin, TimestampMixin


class RunStatus:
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"          # finished with per-record errors
    YIELDED = "yielded"          # stopped by a budget/governor; resumes later
    SUSPENDED = "suspended"      # stopped by the daily ceiling; resumes next quota day
    FAILED = "failed"
    ABANDONED = "abandoned"      # lease expired — the worker died
    CANCELLED = "cancelled"

    TERMINAL = frozenset({SUCCEEDED, PARTIAL, YIELDED, SUSPENDED, FAILED, ABANDONED, CANCELLED})


class ZohoSyncRun(LedgerMixin, Base):
    """One execution slice of one lane of one module — the lease row."""

    __tablename__ = "zoho_sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    module: Mapped[str] = mapped_column(String(64))
    lane: Mapped[str] = mapped_column(String(32))            # scheduled | weekly_full | manual | …
    mode: Mapped[str | None] = mapped_column(String(24))      # engine strategy used
    trigger: Mapped[str] = mapped_column(String(24))          # planner | operator | api
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING)

    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[int] = mapped_column(Integer, default=0)
    listed: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    resurrected: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    unchanged: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    stale_ignored: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    soft_deleted: Mapped[int] = mapped_column(Integer, default=0)
    queued_details: Mapped[int] = mapped_column(Integer, default=0)
    details_saved: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    start_page: Mapped[int | None] = mapped_column(Integer)
    next_page: Mapped[int | None] = mapped_column(Integer)      # set when the slice yielded mid-scan
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    stop_reason: Mapped[str | None] = mapped_column(String(64))
    error_category: Mapped[str | None] = mapped_column(String(32))
    error_fingerprint: Mapped[str | None] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text)

    trace_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[int | None] = mapped_column(BigInteger)
    overrides: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        # DB-enforced singleton: at most one RUNNING run per module × lane.
        Index(
            "uq_zoho_sync_runs_one_running", "module", "lane", unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_zoho_sync_runs_module_lane_started", "module", "lane", "started_at"),
        Index("ix_zoho_sync_runs_status", "status"),
    )


class ZohoSyncCursor(LedgerMixin, Base):
    """Where a lane resumes. Writes are fenced by ``owner_run_id``."""

    __tablename__ = "zoho_sync_cursors"

    module: Mapped[str] = mapped_column(String(64), primary_key=True)
    lane: Mapped[str] = mapped_column(String(32), primary_key=True)
    watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_page: Mapped[int] = mapped_column(Integer, default=1)
    scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    state: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    owner_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ZohoQuotaDay(LedgerMixin, Base):
    """Durable record of each quota day's spend (the governor's Redis counters
    are the live source; this survives Redis loss and feeds analytics)."""

    __tablename__ = "zoho_quota_days"

    pool: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[str] = mapped_column(String(8), primary_key=True)      # YYYYMMDD (quota-day key)
    used: Mapped[int] = mapped_column(Integer, default=0)
    used_background: Mapped[int] = mapped_column(Integer, default=0)
    reserved_peak: Mapped[int] = mapped_column(Integer, default=0)
    by_priority: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    state: Mapped[str | None] = mapped_column(String(16))
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    state_changes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    daily_hard_limit: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ZohoSyncEvent(LedgerMixin, Base):
    """One record-level outcome: "invoice 9549… was updated (status, total)".

    Partitioned by day (RANGE on ``occurred_at``); the primary key therefore
    includes ``occurred_at``. Never stores payloads or secrets — only mapped
    column names and truncated/masked old→new values.
    """

    __tablename__ = "zoho_sync_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    module: Mapped[str] = mapped_column(String(64))
    local_id: Mapped[int | None] = mapped_column(BigInteger)
    zoho_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32))    # inserted | updated | unchanged | tombstoned | …
    direction: Mapped[str] = mapped_column(String(8))      # pull | push | local
    source: Mapped[str | None] = mapped_column(String(48))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    command_id: Mapped[int | None] = mapped_column(BigInteger)
    inbox_id: Mapped[int | None] = mapped_column(BigInteger)
    changed_fields: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    diff: Mapped[dict | None] = mapped_column(JSONB)
    zoho_last_modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    request_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    error_category: Mapped[str | None] = mapped_column(String(32))
    error_fingerprint: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_zoho_sync_events_module_local", "module", "local_id", "occurred_at"),
        Index("ix_zoho_sync_events_module_zoho", "module", "zoho_id", "occurred_at"),
        Index("ix_zoho_sync_events_run", "run_id"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )


class ZohoRetentionPolicy(IntPKMixin, TimestampMixin, Base):
    """How long each kind of control-plane row is kept (most specific wins)."""

    __tablename__ = "zoho_retention_policies"

    table_name: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64), default="*")
    event_class: Mapped[str] = mapped_column(String(32), default="*")   # * | success | failure | approval
    keep_days: Mapped[int] = mapped_column(Integer)
    archive: Mapped[str] = mapped_column(String(16), default="none")   # none | clickhouse
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("table_name", "module", "event_class", name="uq_zoho_retention_scope"),
    )


#: event_type → retention event_class
EVENT_CLASS: dict[str, str] = {
    "inserted": "success",
    "updated": "success",
    "unchanged": "success",
    "resurrected": "success",
    "tombstoned": "success",
    "stale_ignored": "success",
    "push_succeeded": "success",
    "record_error": "failure",
    "push_failed": "failure",
    "push_dead": "failure",
    "conflict_detected": "conflict",
    "approval_requested": "approval",
    "approval_approved": "approval",
    "approval_rejected": "approval",
}

__all__ = [
    "EVENT_CLASS",
    "RunStatus",
    "ZohoQuotaDay",
    "ZohoRetentionPolicy",
    "ZohoSyncCursor",
    "ZohoSyncEvent",
    "ZohoSyncRun",
]
