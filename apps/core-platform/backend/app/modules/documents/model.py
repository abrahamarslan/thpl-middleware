"""Documents model — polymorphic attachments (docs/modules-to-implement/document.md).

Coexists with the render endpoints in this module (Typst PDF flow) and
with app/modules/files (the legacy S3/OCR file table): ``documents`` is the
ATTACHABLE entity — any record (Email, ZohoOrganization, User, ...) gets a
``documents`` list via HasDocumentsMixin.

Design choices from the spec:
  - UUID primary key (no enumeration attacks, no separate document_id col);
  - no ``*_formatted`` columns — presentation strings are Pydantic
    @computed_field, so they can never drift from the raw data;
  - taggable via HasTagsMixin;
  - soft-deleted with the global filter (SoftDeleteFilteredMixin).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import TimestampMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.tags.mixins import HasTagsMixin


class Document(TimestampMixin, SoftDeleteFilteredMixin, HasTagsMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Polymorphic owner (what this document is attached to)
    documentable_id: Mapped[str | None] = mapped_column(String(64), index=True)
    documentable_type: Mapped[str | None] = mapped_column(String(100), index=True)

    # Core file information
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="Bytes")
    mime_type: Mapped[str | None] = mapped_column(String(100))

    # Zoho / external systems
    zoho_id: Mapped[str | None] = mapped_column(String(50))  # partial unique index below
    folder_id: Mapped[str | None] = mapped_column(String(50))
    folder_name: Mapped[str | None] = mapped_column(String(255))

    # Status flags
    document_status: Mapped[str | None] = mapped_column(String(50), default="uploaded", index=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_visible: Mapped[bool | None] = mapped_column(Boolean, default=True)
    display_order: Mapped[int | None] = mapped_column(Integer, default=0)

    # S3 storage
    s3_bucket: Mapped[str | None] = mapped_column(String(100))
    s3_key: Mapped[str | None] = mapped_column(String(500), index=True)
    s3_version_id: Mapped[str | None] = mapped_column(String(100))
    s3_region: Mapped[str | None] = mapped_column(String(50))
    s3_storage_class: Mapped[str | None] = mapped_column(String(50), default="STANDARD")
    s3_etag: Mapped[str | None] = mapped_column(String(100))
    s3_metadata: Mapped[dict | None] = mapped_column(JSONB)

    # Processing & OCR
    processing_status: Mapped[str | None] = mapped_column(String(50), default="pending", index=True)
    processing_results: Mapped[dict | None] = mapped_column(JSONB)
    scanned_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    vendor_name: Mapped[str | None] = mapped_column(String(255), index=True)
    scanned_receipt_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_text: Mapped[dict | None] = mapped_column(JSONB)

    # Security & integrity
    checksum_md5: Mapped[str | None] = mapped_column(String(32))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    virus_scanned: Mapped[bool | None] = mapped_column(Boolean, default=False)
    contains_pii: Mapped[bool | None] = mapped_column(Boolean, default=False)
    access_permissions: Mapped[dict | None] = mapped_column(JSONB)

    # Versioning & metadata
    version: Mapped[str | None] = mapped_column(String(20), default="1.0")
    revision: Mapped[int | None] = mapped_column(Integer, default=1)
    version_history: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    download_count: Mapped[int | None] = mapped_column(Integer, default=0)

    # Upload audit
    uploaded_by_id: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        Index("ix_documents_owner", "documentable_type", "documentable_id"),
        # zoho_id uniqueness only among live rows
        Index(
            "uq_documents_zoho_id_live",
            "zoho_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
