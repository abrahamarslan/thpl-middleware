"""Sync-pipeline observability tables.

Two levels of visibility (complementing Loki logs and Tempo traces):

  zoho_sync_stats  — TABLE-level: one row per module; cursors, counters and
                     the outcome of the last run. Answers "when did invoices
                     last sync and how many rows do we hold?".
  zoho_queue_logs  — ROW-level: one row per queued unit of work (a detail
                     fetch, an inbound upsert batch, an outbound push).
                     Answers "what happened to THIS record on its way
                     through the pipeline?".

Both are plain mirrors-adjacent tables — Debezium can stream them to
ClickHouse for long-term sync analytics exactly like entity tables.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin


class ZohoSyncStat(IntPKMixin, TimestampMixin, Base):
    """Table-level sync statistics — one row per registered module."""

    __tablename__ = "zoho_sync_stats"

    module_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Cursors
    last_sync_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_full_sync_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_incremental_cursor: Mapped[str | None] = mapped_column(
        String(64), comment="Max last_modified_time seen; start of the next incremental window"
    )
    last_zoho_id_synced: Mapped[str | None] = mapped_column(String(50))

    # Lifetime counters
    total_records_synced: Mapped[int | None] = mapped_column(BigInteger, default=0)
    records_created: Mapped[int | None] = mapped_column(BigInteger, default=0)
    records_updated: Mapped[int | None] = mapped_column(BigInteger, default=0)
    skipped_records: Mapped[int | None] = mapped_column(BigInteger, default=0)
    error_count: Mapped[int | None] = mapped_column(BigInteger, default=0)
    run_count: Mapped[int | None] = mapped_column(BigInteger, default=0)

    # Last-run outcome
    last_run_status: Mapped[str | None] = mapped_column(String(20), comment="success | partial | failed | running")
    last_run_mode: Mapped[str | None] = mapped_column(String(20), comment="full | incremental | index")
    last_run_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)

    extra: Mapped[dict | None] = mapped_column(JSONB)


class ZohoQueueLog(IntPKMixin, TimestampMixin, Base):
    """Row-level queue journal — exactly when a record was queued, attempted
    and completed, and by which Celery task."""

    __tablename__ = "zoho_queue_logs"

    module_name: Mapped[str] = mapped_column(String(64), index=True)
    zoho_id: Mapped[str | None] = mapped_column(String(50), index=True)
    local_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # detail_fetch | inbound_upsert | outbound_create | outbound_update | outbound_delete
    operation: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(20), default="queued", index=True, comment="queued | processing | success | failed | skipped"
    )
    attempt: Mapped[int | None] = mapped_column(Integer, default=0)

    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB, comment="Operation context (params, diff, response snippets)")

    __table_args__ = (
        Index("ix_zoho_queue_logs_module_status", "module_name", "status"),
        Index("ix_zoho_queue_logs_module_zoho_id", "module_name", "zoho_id"),
    )
