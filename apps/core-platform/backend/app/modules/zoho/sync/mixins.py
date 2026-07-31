"""ZohoEntityMixin — the strict schema contract for every mirrored entity.

Every table that mirrors a Zoho entity mixes this in (alongside the shared
IntPKMixin / TimestampMixin / SoftDeleteMixin from app/database/mixins.py):

    class ZohoOrganization(IntPKMixin, TimestampMixin, SoftDeleteMixin,
                           ZohoEntityMixin, Base):
        __tablename__ = "zoho_organizations"
        ...business columns...

Schema doctrine:
  - EVERY business/sync column here is nullable=True — an incomplete Zoho
    payload must never violate a constraint and fail the sync.
  - ``zoho_raw`` keeps the full untouched document (JSONB) so a Zoho schema
    change never loses data and Debezium streams the complete record to
    Kafka/ClickHouse regardless of which columns we extracted.
  - ``custom_fields`` uses Postgres hstore for Zoho's dynamic custom fields
    (flat text map, GIN-indexable); the raw array stays inside zoho_raw.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import HSTORE, JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class SyncStatus(str, Enum):
    """Values of the ``sync_status`` column (String, not a DB enum, so new
    states never require a migration)."""

    PENDING = "pending"        # never synced
    QUEUED = "queued"          # a queue-log entry exists, worker not started
    SYNCING = "syncing"        # a worker is processing this row
    SYNCED = "synced"          # in sync with Zoho
    ERROR = "error"            # last attempt failed (see sync_error)
    CONFLICT = "conflict"      # inbound + outbound changed simultaneously
    DELETED = "deleted"        # deleted upstream / delete pushed to Zoho


class ZohoEntityMixin:
    """Cross-cutting columns for Zoho-mirrored entities (all nullable)."""

    # ── Core identifiers ────────────────────────────────────────────────────
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), index=True, comment="Zoho primary key; NULL until first outbound push succeeds"
    )
    code: Mapped[str | None] = mapped_column(
        String(50), unique=True, comment="Short human reference (unique when set; NULLs don't collide)"
    )
    description: Mapped[str | None] = mapped_column(Text)

    # ── Sync management & observability ─────────────────────────────────────
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(20), default=SyncStatus.PENDING.value, index=True)
    sync_error: Mapped[str | None] = mapped_column(Text)
    sync_attempt_count: Mapped[int | None] = mapped_column(Integer, default=0)
    sync_logs: Mapped[list | None] = mapped_column(JSONB, comment="Rolling per-row journal of sync events")

    # ── Status & tracking flags ─────────────────────────────────────────────
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_blocked: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_featured: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_promoted: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_sponsored: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_partnered: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_visible: Mapped[bool | None] = mapped_column(Boolean, default=True)
    show_in_menu: Mapped[bool | None] = mapped_column(Boolean, default=True)
    display_order: Mapped[int | None] = mapped_column(Integer, default=0)
    menu_order: Mapped[int | None] = mapped_column(Integer, default=0)

    # ── Extensions ──────────────────────────────────────────────────────────
    # Attribute is metadata_ because `metadata` is reserved on Declarative.
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, comment="Flexible extension data")
    document_id: Mapped[str | None] = mapped_column(String(50), comment="Optional link into the documents module")
    custom_fields: Mapped[dict | None] = mapped_column(
        HSTORE, comment="Zoho custom fields flattened to text (raw array in zoho_raw)"
    )
    zoho_raw: Mapped[dict | None] = mapped_column(JSONB, comment="Full untouched Zoho document")

    @declared_attr.directive
    def __mapper_args__(cls):  # noqa: N805
        return {}

    # ── Row-level journal helper ────────────────────────────────────────────
    def append_sync_log(self, event: str, **details) -> None:
        """Append one entry to the rolling sync_logs journal (kept to 50)."""
        from datetime import UTC

        entry = {"event": event, "at": datetime.now(UTC).isoformat(), **details}
        logs = list(self.sync_logs or [])
        logs.append(entry)
        self.sync_logs = logs[-50:]
