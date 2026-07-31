import math
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, computed_field

from app.modules.tags.schema import TagOut


# ── PDF rendering (Gotenberg flow) ──────────────────────────────────────────

class RenderRequest(BaseModel):
    html: str
    filename: str = "document.pdf"


class TaskSubmitted(BaseModel):
    task_id: str
    status: str = "queued"


class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


# ── Polymorphic document attachments ────────────────────────────────────────

class DocumentBase(BaseModel):
    file_name: str
    file_type: str
    file_size: int
    mime_type: str | None = None
    document_status: str = "uploaded"
    processing_status: str = "pending"
    is_active: bool = True
    is_visible: bool = True
    display_order: int = 0


class DocumentCreate(DocumentBase):
    """Register a document AFTER the bytes were uploaded to S3."""

    documentable_id: str | None = None
    documentable_type: str | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    s3_region: str | None = None
    s3_etag: str | None = None
    checksum_md5: str | None = None
    checksum_sha256: str | None = None
    metadata_: dict | None = None


class DocumentOut(DocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    documentable_id: str | None = None
    documentable_type: str | None = None
    zoho_id: str | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    scanned_amount: float | None = None
    vendor_name: str | None = None
    metadata_: dict | None = None
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = []

    # No *_formatted columns in the DB — presentation is computed on the fly
    # so it can never drift from the raw value (document.md rationale).
    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_size_formatted(self) -> str:
        if not self.file_size:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        i = min(int(math.floor(math.log(self.file_size, 1024))), len(units) - 1)
        return f"{round(self.file_size / (1024 ** i), 2)} {units[i]}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_processable(self) -> bool:
        return (self.file_type or "").lower() in {"pdf", "doc", "docx", "png", "jpg", "jpeg"}


class AttachDocumentsRequest(BaseModel):
    """Attach existing documents to an entity (with per-doc metadata)."""

    documentable_type: str
    documentable_id: str
    document_ids: list[UUID]
    metadata_by_id: dict[UUID, dict] = {}
