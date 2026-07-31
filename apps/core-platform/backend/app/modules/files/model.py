"""Files model — uploaded/scanned documents (S3-backed, OCR-aware).

Async port of the provided FileEntity, adapted to project conventions:
  - inherits the shared mixins (IntPK, Tenant, Timestamp, SoftDelete) instead
    of redeclaring id/tenant_id/created_at/updated_at/deleted_at;
  - JSON -> JSONB (Postgres-only stack);
  - timestamps are DB-authoritative (server_default) via TimestampMixin.
Every column from the original design is preserved.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, SoftDeleteMixin, TenantMixin, TimestampMixin


class FileEntity(IntPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "files"

    file_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True, comment="Public UUID"
    )

    # Polymorphic association (Laravel's morphs): which record this file belongs to.
    fileable_type: Mapped[str | None] = mapped_column(String(100), index=True)
    fileable_id: Mapped[str | None] = mapped_column(String(50), index=True)

    # Integrations & folders
    zoho_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    folder_id: Mapped[str | None] = mapped_column(String(50))
    folder_name: Mapped[str | None] = mapped_column(String(255))

    # File info
    file_name: Mapped[str] = mapped_column(String(255), index=True)
    file_type: Mapped[str] = mapped_column(String(50), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer, comment="Size in bytes")

    # Scanned / OCR data
    document_scan_status: Mapped[str | None] = mapped_column(String(100))
    scanned_amount: Mapped[Decimal] = mapped_column(Numeric(15, 8), default=Decimal("0.00"))
    vendor_name: Mapped[str | None] = mapped_column(String(255), index=True)
    scanned_receipt_date: Mapped[date | None] = mapped_column(Date)

    # Cloud storage (S3)
    s3_bucket: Mapped[str | None] = mapped_column(String(100), index=True)
    s3_key: Mapped[str | None] = mapped_column(String(500), index=True)
    s3_version_id: Mapped[str | None] = mapped_column(String(100))
    s3_region: Mapped[str | None] = mapped_column(String(50))
    s3_metadata: Mapped[dict | None] = mapped_column(JSONB)
    s3_storage_class: Mapped[str | None] = mapped_column(String(50))

    # Security & processing
    processing_status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    checksum_md5: Mapped[str | None] = mapped_column(String(32))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    virus_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    virus_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contains_pii: Mapped[bool] = mapped_column(Boolean, default=False)

    # Status flags
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Audit & upload tracking
    source: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[str | None] = mapped_column(String(255), index=True)
    uploaded_by_id: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        Index("ix_file_type_processing_status", "file_type", "processing_status"),
        Index("ix_created_at_processing_status", "created_at", "processing_status"),
    )
