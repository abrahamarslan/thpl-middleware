"""Reusable declarative model mixins.

Design decision — *mixins vs utilities*:
  - Cross-cutting COLUMNS (timestamps, soft delete, tenant, audit-user) are
    best expressed as **mixins**: they are pure schema, compose cleanly, and
    every table wants the same shape. That is what lives here.
  - Cross-cutting BEHAVIOUR (recording an activity/audit entry) is best
    expressed as a **utility/service** (see app/modules/activity/recorder.py),
    NOT a mixin or SQLAlchemy event listener — explicit recording is testable,
    transaction-aware, and never fires inside an unexpected unit of work.

Mix into a model in this order (most-specific first, Base last):

    class Foo(IntPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
        __tablename__ = "foo"
        ...
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class IntPKMixin:
    """Surrogate big-integer primary key (internal; never exposed in APIs)."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """DB-authoritative created/updated timestamps (timezone-aware, UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Soft delete via a nullable deleted_at. Queries must filter deleted_at IS NULL."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TenantMixin:
    """Optional SaaS tenant scoping. Nullable so single-tenant deploys ignore it."""

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)


class AuditUserMixin:
    """Who created / updated / soft-deleted the row (references users.id)."""

    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    deleted_by: Mapped[int | None] = mapped_column(BigInteger)
