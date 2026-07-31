"""Files module — transport schemas (DTOs).

Keeps the original DTO design (slim list view, full response with on-the-fly
formatted columns), adapted to the project's create/update conventions.
"""

import math
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class FileBase(BaseModel):
    file_name: str
    file_type: str
    file_size: int = Field(ge=0)
    source: str
    zoho_id: str | None = None
    folder_id: str | None = None
    vendor_name: str | None = None


class FileCreate(FileBase):
    """Payload for creating a file record (metadata; bytes live in S3)."""

    tenant_id: uuid.UUID | None = None
    mime_type: str | None = None
    uploaded_by_id: str | None = None
    fileable_type: str | None = None
    fileable_id: str | None = None
    s3_bucket: str
    s3_key: str
    s3_region: str | None = None
    s3_storage_class: str | None = None
    contains_pii: bool = False


class FileStatusUpdate(BaseModel):
    """Partial update for processing/scan lifecycle transitions."""

    processing_status: str | None = None
    document_scan_status: str | None = None
    scanned_amount: Decimal | None = None
    scanned_receipt_date: date | None = None
    vendor_name: str | None = None
    checksum_md5: str | None = None
    checksum_sha256: str | None = None
    virus_scanned: bool | None = None
    virus_scanned_at: datetime | None = None
    is_verified: bool | None = None
    is_blocked: bool | None = None


class FileSlimOut(BaseModel):
    """Slim model for list views / dropdowns."""

    model_config = ConfigDict(from_attributes=True)

    file_id: uuid.UUID
    file_name: str
    is_active: bool
    processing_status: str


class FileOut(FileBase):
    """Full detail model, with formatted columns generated on the fly."""

    model_config = ConfigDict(from_attributes=True)

    file_id: uuid.UUID
    mime_type: str | None = None
    processing_status: str
    document_scan_status: str | None = None
    is_active: bool
    is_verified: bool
    is_blocked: bool
    contains_pii: bool
    virus_scanned: bool
    scanned_amount: Decimal = Decimal("0.00")
    scanned_receipt_date: date | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    tenant_id: uuid.UUID | None = None
    uploaded_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # --- formatted columns (computed, read-only) ---

    @computed_field
    @property
    def file_size_formatted(self) -> str:
        if not self.file_size:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        i = int(math.floor(math.log(self.file_size, 1024)))
        i = min(i, len(units) - 1)
        return f"{round(self.file_size / math.pow(1024, i), 2)} {units[i]}"

    @computed_field
    @property
    def created_at_formatted(self) -> str:
        return self.created_at.strftime("%B %d, %Y %H:%M:%S")

    @computed_field
    @property
    def scanned_amount_formatted(self) -> str:
        return f"${self.scanned_amount:,.2f}" if self.scanned_amount else "$0.00"

    @computed_field
    @property
    def scanned_receipt_date_formatted(self) -> str | None:
        return self.scanned_receipt_date.strftime("%B %d, %Y") if self.scanned_receipt_date else None


class FileListFilters(BaseModel):
    file_type: str | None = None
    processing_status: str | None = None
    vendor_name: str | None = None
    fileable_type: str | None = None
    fileable_id: str | None = None
    is_active: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
