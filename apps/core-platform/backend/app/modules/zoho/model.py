"""SQLAlchemy models for the Zoho integration (model layer)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base


class ZohoSyncState(Base):
    """Tracks the last successful sync per Zoho entity (items, contacts, ...).

    Celery Beat schedules periodic syncs; workers read/update this row to
    perform incremental pulls instead of full refetches.
    """

    __tablename__ = "zoho_sync_state"

    entity: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    detail: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
