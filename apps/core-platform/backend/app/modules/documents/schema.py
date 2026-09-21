import math
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, computed_field

from app.modules.documents.enums import (
    DocumentLinkableType,
    DocumentLinkRole,
    DocumentPageSide,
    DocumentVerificationMethod,
    FileStorageProvider,
    PersonnelType,
    SourceChannel,
)
from app.modules.documents.seed import GENERAL_TYPE_CODE
from app.modules.tags.schema import TagOut


# ── PDF rendering (Typst flow) ──────────────────────────────────────────────

class RenderRequest(BaseModel):
    """Compile Typst markup to PDF (async via Celery).

    Prefer ``sys_inputs`` over interpolating data into ``source``::

        source = '#let invoice = json(bytes(sys.inputs.invoice))\n#invoice.number'
        sys_inputs = {"invoice": '{"number": "INV-1"}'}
    """

    source: str
    filename: str = "document.pdf"
    sys_inputs: dict[str, str] | None = None


class TaskSubmitted(BaseModel):
    task_id: str
    status: str = "queued"


class TaskStatus(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


# ── Document catalog ────────────────────────────────────────────────────────

class DocumentTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    display_name: str
    category: str
    description: str | None = None
    requires_front_and_back: bool
    has_expiry: bool
    default_validity_days: int | None = None
    allows_full_number_storage: bool
    agent_type_requirement: dict[str, str]
    regulatory_reference: str | None = None
    sort_order: int
    deactivation_date: datetime | None = None


# ── Requests ────────────────────────────────────────────────────────────────

class FileIn(BaseModel):
    """Register a file AFTER its bytes reached object storage."""

    file_name: str = Field(min_length=1, max_length=255)
    file_key: str = Field(min_length=1, description="Object key / path (local_disk: the path)")
    file_storage_provider: FileStorageProvider = FileStorageProvider.S3
    page_side: DocumentPageSide = DocumentPageSide.NOT_APPLICABLE
    page_index: int | None = Field(None, ge=0, description="Defaults to the next free position")
    mime_type: str | None = Field(None, max_length=100)
    file_size_bytes: int | None = Field(None, ge=0)
    file_hash_sha256: str | None = Field(None, pattern=r"^[0-9a-fA-F]{64}$")
    storage_bucket: str | None = Field(None, max_length=100)
    storage_region: str | None = Field(None, max_length=50)
    storage_class: str | None = Field(None, max_length=50)
    storage_version_id: str | None = Field(None, max_length=100)
    etag: str | None = Field(None, max_length=100)
    storage_metadata: dict | None = None
    source_channel: SourceChannel | None = None
    zoho_id: str | None = Field(None, max_length=50)
    folder_id: str | None = Field(None, max_length=50)
    folder_name: str | None = Field(None, max_length=255)


class LinkIn(BaseModel):
    linkable_type: DocumentLinkableType
    linkable_id: int = Field(gt=0)
    link_role: DocumentLinkRole = DocumentLinkRole.OWNER
    is_primary: bool = False
    sort_order: int = 0
    context: dict | None = None


class DocumentCreate(BaseModel):
    """Register a document: its type, printed metadata, files and owners.

    With no ``files`` the document waits in ``pending_upload``; it becomes
    ``uploaded`` once the type's file requirement is met (one file, or a front
    AND a back for two-sided types).
    """

    document_type_code: str = Field(default=GENERAL_TYPE_CODE, max_length=64)
    # Never echoed, never logged. Stored masked; the full number only for types
    # that allow it AND only when DOCUMENT_NUMBER_ENCRYPTION_KEY is configured.
    document_number: SecretStr | None = None
    issuing_authority: str | None = Field(None, max_length=255)
    issuing_state: str | None = Field(None, max_length=100)
    issued_date: date | None = None
    expiry_date: date | None = None
    personnel_type: PersonnelType | None = Field(
        None, description="Sets is_mandatory from the type's requirement for this personnel type",
    )
    retention_expiry_date: date | None = None
    ocr_extracted_data: dict | None = None
    files: list[FileIn] = []
    links: list[LinkIn] = []


class AddFileRequest(FileIn):
    pass


class ResubmitRequest(BaseModel):
    """A new version of a rejected / expired / resubmission-required document."""

    files: list[FileIn] = Field(min_length=1)
    document_number: SecretStr | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    issuing_authority: str | None = Field(None, max_length=255)
    issuing_state: str | None = Field(None, max_length=100)


class AttachDocumentsRequest(BaseModel):
    """Link existing documents to an entity (an email's attachments, …)."""

    linkable_type: DocumentLinkableType
    linkable_id: int = Field(gt=0)
    document_ids: list[UUID]
    link_role: DocumentLinkRole = DocumentLinkRole.ATTACHMENT
    context_by_id: dict[UUID, dict] = {}


class VerifyRequest(BaseModel):
    method: DocumentVerificationMethod = DocumentVerificationMethod.MANUAL_REVIEW
    remarks: str | None = None
    third_party_provider: str | None = Field(None, max_length=50)
    third_party_reference_id: str | None = Field(None, max_length=255)
    third_party_cost_inr: Decimal | None = Field(None, ge=0, max_digits=8, decimal_places=2)
    provider_payload: dict | None = Field(None, description="Raw provider response, kept for audit and disputes")


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1)


class RemarksRequest(BaseModel):
    remarks: str | None = None


# ── Responses ───────────────────────────────────────────────────────────────

class DocumentFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(validation_alias="uuid")
    page_side: str
    page_index: int
    is_primary: bool
    file_name: str
    mime_type: str | None = None
    file_size_bytes: int | None = None
    file_hash_sha256: str | None = None
    file_storage_provider: str
    file_key: str
    storage_bucket: str | None = None
    virus_scanned: bool
    processing_status: str
    uploaded_at: datetime | None = None
    source_channel: str | None = None
    created_at: datetime

    # No *_formatted columns in the DB — presentation is computed on the fly so
    # it can never drift from the raw value (docs/modules-to-implement/document.md).
    @computed_field  # type: ignore[prop-decorator]
    @property
    def file_size_formatted(self) -> str:
        if not self.file_size_bytes:
            return "0 B"
        units = ("B", "KB", "MB", "GB", "TB")
        i = min(int(math.floor(math.log(self.file_size_bytes, 1024))), len(units) - 1)
        return f"{round(self.file_size_bytes / (1024 ** i), 2)} {units[i]}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_processable(self) -> bool:
        ext = self.file_name.rsplit(".", 1)[-1].lower() if "." in self.file_name else ""
        return ext in {"pdf", "doc", "docx", "png", "jpg", "jpeg"}


class DocumentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(validation_alias="uuid")
    linkable_type: str
    linkable_id: int
    link_role: str
    is_primary: bool
    sort_order: int
    context: dict | None = None
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(validation_alias="uuid")
    document_type_code: str
    document_type_name: str
    document_purpose: str
    status: str

    verification_status: str
    is_verified: bool
    verification_method: str | None = None
    verified_by: int | None = None
    verified_at: datetime | None = None
    rejection_reason: str | None = None

    document_number_masked: str | None = None
    issuing_authority: str | None = None
    issuing_state: str | None = None
    issued_date: date | None = None
    expiry_date: date | None = None
    is_mandatory: bool

    version_number: int
    is_latest_version: bool
    resubmission_count: int

    deactivation_date: datetime | None = None
    deactivation_reason: str | None = None
    retention_expiry_date: date | None = None

    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    files: list[DocumentFileOut] = []
    links: list[DocumentLinkOut] = []
    tags: list[TagOut] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_expired(self) -> bool:
        return self.expiry_date is not None and self.expiry_date < date.today()


class VerificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    previous_status: str | None = None
    new_status: str | None = None
    actor_type: str
    performed_by: int | None = None
    performed_by_name: str | None = None
    performed_at: datetime
    remarks: str | None = None
