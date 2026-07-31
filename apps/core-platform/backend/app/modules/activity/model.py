"""Activity / audit-trail model.

NOT to be confused with operational logging (app/core/logging/ -> Loki).
That answers "what is the process doing?"; THIS answers the business/compliance
question "who did what to which record, and when?" — a persisted, queryable,
user-facing audit trail.

Append-only by design: rows are written once and never updated or deleted
(no updated_at, no soft delete). `request_id` ties each entry back to the
operational logs/traces in Loki/Tempo for the same request.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TenantMixin


class ActivityLog(IntPKMixin, TenantMixin, Base):
    __tablename__ = "activity_logs"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True,
        comment="Public identifier",
    )

    # What happened — dotted verb, e.g. 'user.login', 'file.uploaded'.
    action: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default="success", comment="success | failure")
    description: Mapped[str | None] = mapped_column(Text)

    # Who did it (snapshot — survives later user edits/deletes).
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="users.id")
    actor_type: Mapped[str] = mapped_column(String(20), default="user", comment="user | system | service")
    actor_label: Mapped[str | None] = mapped_column(String(255), comment="email/name snapshot")

    # What it was done to (polymorphic; subject_id is string to allow int or uuid).
    subject_type: Mapped[str | None] = mapped_column(String(100), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Field-level before/after diff and any extra structured context.
    changes: Mapped[dict | None] = mapped_column(JSONB)
    context: Mapped[dict | None] = mapped_column(JSONB)

    # Correlation with operational logs/traces + provenance.
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_activity_subject", "subject_type", "subject_id"),
        Index("ix_activity_action_created", "action", "created_at"),
        Index("ix_activity_tenant_created", "tenant_id", "created_at"),
    )
