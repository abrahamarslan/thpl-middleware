"""Document module — the logical document, its files, what it belongs to, and its trail.

    document_types              GLOBAL   the catalog: AADHAAR, DRIVING_LICENSE, GENERAL, …
    documents                   ENTITY   the LOGICAL document: type, verification, printed
                                         metadata, versioning, retention
    document_files              ENTITY   the PHYSICAL files/pages (front / back / extra …)
    document_links              ENTITY   polymorphic pivot: what the document belongs to, in what role
    document_verification_logs  LEDGER   immutable trail of every status transition

Why a logical document + page files: a two-sided document (Aadhaar, DL) is ONE
document with TWO files. Splitting it into ``AADHAAR_FRONT`` / ``AADHAAR_BACK``
types made two disconnected rows whose sides could be mismatched with no shared
verification. Here the type is ``AADHAAR`` (``requires_front_and_back``) and the
sides are pages of one row, so the pair is verified and versioned as a set.

Why a pivot and not ``owner_type`` / ``owner_id`` on the document: one document
can belong to several entities (a vehicle RC scan to the vehicle AND its owner),
with exactly one of them in the ``owner`` role. ``PolymorphicOwnerMixin`` says
"this row belongs to ONE entity" — the wrong claim here.

Generic files (email attachments, exports) are documents of the ``GENERAL`` type:
one row shape for everything, no second file table.

Scoping: ``documents``, ``document_files`` and ``document_links`` are tenant
entities. Both children carry a composite FK ``(tenant_id, document_id)`` →
``documents (tenant_id, id)``, so the DATABASE guarantees a file or link can never
point at another tenant's document. ``document_types`` is the platform-wide catalog
(like countries) and carries no tenant scoping; add ``tenant_id`` and change the
``code`` uniqueness if per-tenant catalogs are ever required.

Aadhaar: the FRONT/BACK *images* are files of a logical AADHAAR document. The raw
number is NEVER stored — ``document_types.allows_full_number_storage`` is false and
the service refuses to fill ``document_number_full_encrypted`` for such a type. The
masked number and the UIDAI Aadhaar-Data-Vault reference belong to the KYC module.

What our mixins replace (the reference design declared each by hand): tenancy,
audit (+ ``*_name``), ``status``, ``row_version``, ``app_*`` (TenantEntityMixin);
``verified_*`` / ``verification_*`` (VerificationMixin); the ``is_active`` kill
switch and ``deactivated_*`` (DeactivationMixin — ``deactivation_date IS NULL`` is
"active"); ``deleted_*`` (SoftDeleteFilteredMixin); attach/detach audit of a link
(``created_*`` / ``deleted_*``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    IntPKMixin,
    LedgerMixin,
    RowVersionMixin,
    TenantEntityMixin,
    TimestampMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.enums import (
    DocumentAuditAction,
    DocumentLinkRole,
    DocumentPageSide,
    DocumentPurpose,
    DocumentVerificationMethod,
    DocumentVerificationStatus,
    FileProcessingStatus,
    FileStorageProvider,
    SourceChannel,
    VerificationActorType,
    values,
)
from app.modules.tags.mixins import HasTagsMixin

_STATUS_SQL = "'active','suspended','archived'"


class DocumentType(IntPKMixin, AuditMixin, RowVersionMixin, AppMetaMixin, TimestampMixin, DeactivationMixin, Base):
    """One canonical document type the platform can request (see ``seed.py``)."""

    __tablename__ = "document_types"
    __table_args__ = (
        CheckConstraint(f"category IN ({values(DocumentPurpose)})", name="chk_document_type_category"),
        CheckConstraint("default_validity_days IS NULL OR default_validity_days > 0",
                        name="chk_document_type_validity_days"),
        {"comment": "Catalog of document kinds (platform-wide reference data)."},
    )

    code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        comment="Stable machine code, e.g. AADHAAR, VEHICLE_INSURANCE, GENERAL",
    )
    display_name: Mapped[str] = mapped_column(
        String(150), nullable=False, comment="Human-readable name shown in the app/UI",
    )
    category: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="Purpose taxonomy (identity_proof / address_proof / vehicle_compliance / …)",
    )
    description: Mapped[str | None] = mapped_column(Text, comment="Guidance for uploaders")

    requires_front_and_back: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="True when both faces must be uploaded (Aadhaar, DL)",
    )
    has_expiry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Whether this document carries an expiry date",
    )
    default_validity_days: Mapped[int | None] = mapped_column(
        Integer, comment="Pre-fills expiry_date and drives re-verification reminders",
    )
    allows_full_number_storage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="False = only the masked / last-4 number may be stored (Aadhaar: UIDAI restricts full "
                "numbers to entities running a certified Aadhaar Data Vault)",
    )
    agent_type_requirement: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment='PersonnelType.value -> "mandatory" | "optional" | "not_applicable"',
    )
    regulatory_reference: Mapped[str | None] = mapped_column(
        Text, comment="e.g. 'Motor Vehicles Act 1988 s.3 (commercial DL)'",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Order in the checklist / upload UI",
    )

    def requirement_for(self, personnel_type: str | None) -> str:
        """``mandatory`` / ``optional`` / ``not_applicable`` for a personnel type."""
        return (self.agent_type_requirement or {}).get(personnel_type or "", "optional")

    def __repr__(self) -> str:
        return f"<DocumentType {self.code}>"


class Document(
    BigIntPKWithUUIDMixin, TenantEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, HasTagsMixin, Base,
):
    """A logical document (one per subject + type + version), held by 1..N files."""

    __tablename__ = "documents"
    __table_args__ = (
        # Target of the composite FKs of files, links, logs and the version chain.
        UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "supersedes_document_id"], ["documents.tenant_id", "documents.id"],
            name="fk_documents_supersedes", ondelete="RESTRICT",
        ),
        CheckConstraint(f"document_purpose IN ({values(DocumentPurpose)})", name="chk_document_purpose"),
        CheckConstraint(f"verification_status IN ({values(DocumentVerificationStatus)})",
                        name="chk_document_verification_status"),
        CheckConstraint(f"verification_method IS NULL OR verification_method IN ({values(DocumentVerificationMethod)})",
                        name="chk_document_verification_method"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="chk_document_status"),
        # is_verified is a cache of the status; the database keeps it honest.
        CheckConstraint("is_verified = (verification_status = 'verified')", name="chk_document_is_verified_cache"),
        CheckConstraint("version_number >= 1", name="chk_document_version_number"),
        CheckConstraint("resubmission_count >= 0", name="chk_document_resubmission_count"),
        CheckConstraint("expiry_date IS NULL OR issued_date IS NULL OR expiry_date >= issued_date",
                        name="chk_document_dates"),
        CheckConstraint("supersedes_document_id IS NULL OR supersedes_document_id <> id",
                        name="chk_document_not_own_predecessor"),
        # "Which of this tenant's documents are of type X / in state Y" — the checklist reads.
        Index("ix_documents_type", "tenant_id", "document_type_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_documents_verification", "tenant_id", "verification_status",
              postgresql_where=text("deleted_at IS NULL")),
        # Expiry reminders scan only what can expire.
        Index("ix_documents_expiry", "tenant_id", "expiry_date",
              postgresql_where=text("deleted_at IS NULL AND expiry_date IS NOT NULL")),
        Index("ix_documents_retention", "retention_expiry_date",
              postgresql_where=text("retention_expiry_date IS NOT NULL")),
        # A document is superseded at most once: two concurrent resubmissions of
        # the same version cannot both create "version 2".
        Index("uq_documents_supersedes", "supersedes_document_id", unique=True,
              postgresql_where=text("supersedes_document_id IS NOT NULL AND deleted_at IS NULL")),
        {"comment": "Logical document: type, verification, printed metadata, versioning, retention."},
    )

    document_type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("document_types.id", ondelete="RESTRICT"), nullable=False,
        comment="The logical type (AADHAAR, DRIVING_LICENSE, GENERAL, …)",
    )
    document_purpose: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="Denormalised type category, for fast filtering",
    )

    # ---- number (belongs to the logical document, not a page) -------------
    document_number_masked: Mapped[str | None] = mapped_column(
        String(100), comment="Masked / partial number, for search and de-duplication",
    )
    document_number_full_encrypted: Mapped[str | None] = mapped_column(
        Text, comment="pgcrypto-encrypted full number. MUST stay NULL when the type has "
                      "allows_full_number_storage = false (Aadhaar)",
    )

    # ---- metadata as printed on the document ------------------------------
    issuing_authority: Mapped[str | None] = mapped_column(String(255), comment="Authority that issued it")
    issuing_state: Mapped[str | None] = mapped_column(String(100), comment="State / region that issued it")
    issued_date: Mapped[dt.date | None] = mapped_column(Date, comment="Issue date printed on the document")
    expiry_date: Mapped[dt.date | None] = mapped_column(Date, comment="Expiry date printed on the document")

    # ---- verification ------------------------------------------------------
    # Overrides VerificationMixin.verification_status: the lifecycle here is
    # longer ('resubmission_required' is 21 characters) and starts before any
    # file exists. verified_by / verified_at / verification_method /
    # verification_data come from the mixin — verification_data holds the raw
    # third-party payload kept for audit and disputes.
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DocumentVerificationStatus.PENDING_UPLOAD.value,
        server_default=text(f"'{DocumentVerificationStatus.PENDING_UPLOAD.value}'"), index=True,
        comment="not_uploaded / pending_upload / uploaded / in_review / verified / rejected / expired / "
                "resubmission_required",
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, comment="Why the document was rejected")
    ocr_extracted_data: Mapped[dict | None] = mapped_column(
        JSONB, comment="Raw OCR / extraction payload, kept for audit",
    )
    third_party_verification_provider: Mapped[str | None] = mapped_column(
        String(50), comment="karza, idfy, hyperverge, signzy, digilocker, parivahan …",
    )
    third_party_verification_reference_id: Mapped[str | None] = mapped_column(
        String(255), comment="Provider transaction / reference id",
    )
    third_party_verification_cost_inr: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), comment="Cost charged by the provider for this verification",
    )

    # ---- versioning (a re-upload is a new row) ----------------------------
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="Increments on each resubmission",
    )
    is_latest_version: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="True for the current version of its chain",
    )
    supersedes_document_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The previous version this one replaces (composite FK with tenant_id)",
    )
    resubmission_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="How many times this document was resubmitted",
    )

    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Whether it is mandatory for the owner's role (snapshot of the type requirement)",
    )
    retention_expiry_date: Mapped[dt.date | None] = mapped_column(
        Date, comment="DPDP Act 2023 retention: purge / anonymise after this date",
    )

    document_type: Mapped[DocumentType] = relationship(lazy="joined")
    files: Mapped[list[DocumentFile]] = relationship(
        back_populates="document", lazy="selectin", order_by="DocumentFile.page_index", viewonly=True,
    )
    links: Mapped[list[DocumentLink]] = relationship(
        back_populates="document", lazy="selectin", order_by="DocumentLink.sort_order", viewonly=True,
    )

    @property
    def document_type_code(self) -> str:
        return self.document_type.code

    @property
    def document_type_name(self) -> str:
        return self.document_type.display_name

    @property
    def is_expired(self) -> bool:
        return self.expiry_date is not None and self.expiry_date < dt.date.today()

    @property
    def primary_file(self) -> DocumentFile | None:
        return next((f for f in self.files if f.is_primary), self.files[0] if self.files else None)

    def __repr__(self) -> str:
        return f"<Document id={self.id} v{self.version_number} {self.verification_status}>"


class DocumentFile(
    BigIntPKWithUUIDMixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """One physical file / page of a logical document (front, back, extra …)."""

    __tablename__ = "document_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="fk_document_files_tenant_document", ondelete="CASCADE",
        ),
        CheckConstraint("file_key <> ''", name="chk_document_file_key"),
        CheckConstraint(f"page_side IN ({values(DocumentPageSide)})", name="chk_document_file_page_side"),
        CheckConstraint(f"file_storage_provider IN ({values(FileStorageProvider)})",
                        name="chk_document_file_storage_provider"),
        CheckConstraint(f"source_channel IS NULL OR source_channel IN ({values(SourceChannel)})",
                        name="chk_document_file_source_channel"),
        CheckConstraint(f"processing_status IN ({values(FileProcessingStatus)})",
                        name="chk_document_file_processing_status"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="chk_document_file_status"),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="chk_document_file_size"),
        CheckConstraint("page_index >= 0", name="chk_document_file_page_index"),
        Index("ix_document_files_document", "document_id", "page_side", postgresql_where=text("deleted_at IS NULL")),
        # One primary / display file per logical document.
        Index("uq_document_files_one_primary", "document_id", unique=True,
              postgresql_where=text("is_primary AND deleted_at IS NULL")),
        # One front and one back per document; extra pages are unbounded.
        Index("uq_document_files_side", "document_id", "page_side", unique=True,
              postgresql_where=text("page_side IN ('front','back') AND deleted_at IS NULL")),
        # Integrity and duplicate-upload detection.
        Index("ix_document_files_hash", "tenant_id", "file_hash_sha256",
              postgresql_where=text("deleted_at IS NULL AND file_hash_sha256 IS NOT NULL")),
        Index("uq_document_files_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        {"comment": "Physical files / pages of a logical document."},
    )

    document_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The logical document (composite FK with tenant_id)",
    )
    page_side: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentPageSide.NOT_APPLICABLE.value,
        server_default=text(f"'{DocumentPageSide.NOT_APPLICABLE.value}'"),
        comment="front / back / single_page / extra_page / not_applicable",
    )
    page_index: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
        comment="Order within the document (front = 0, back = 1, extras follow)",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="The display file of the document (one per document)",
    )

    # ---- what the bytes are ------------------------------------------------
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Original (client) file name")
    mime_type: Mapped[str | None] = mapped_column(String(100), comment="e.g. image/jpeg, application/pdf")
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_hash_sha256: Mapped[str | None] = mapped_column(
        String(64), comment="sha256 (64 hex) of the bytes: integrity + duplicate-upload detection",
    )

    # ---- where the bytes are (provider-neutral; S3 today) ------------------
    file_storage_provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FileStorageProvider.S3.value,
        server_default=text(f"'{FileStorageProvider.S3.value}'"), comment="Object store holding the file",
    )
    file_key: Mapped[str] = mapped_column(Text, nullable=False, comment="Object key / path (local_disk: the path)")
    storage_bucket: Mapped[str | None] = mapped_column(String(100))
    storage_region: Mapped[str | None] = mapped_column(String(50))
    storage_class: Mapped[str | None] = mapped_column(String(50), comment="e.g. STANDARD")
    storage_version_id: Mapped[str | None] = mapped_column(String(100), comment="Object version, when versioned")
    etag: Mapped[str | None] = mapped_column(String(100))
    storage_metadata: Mapped[dict | None] = mapped_column(JSONB, comment="Provider-specific extras")

    # ---- per-file pipeline (virus scan, OCR) -------------------------------
    virus_scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FileProcessingStatus.PENDING.value,
        server_default=text(f"'{FileProcessingStatus.PENDING.value}'"),
    )
    processing_results: Mapped[dict | None] = mapped_column(JSONB, comment="Pipeline output, incl. extracted text")

    # ---- upload provenance -------------------------------------------------
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id who uploaded (NULL = system)")
    uploaded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source_channel: Mapped[str | None] = mapped_column(
        String(40), comment="mobile_app / web_portal / admin_upload / field_agent_assisted_upload",
    )

    # ---- external systems --------------------------------------------------
    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Zoho document id (per file)")
    folder_id: Mapped[str | None] = mapped_column(String(50))
    folder_name: Mapped[str | None] = mapped_column(String(255))

    document: Mapped[Document] = relationship(back_populates="files", lazy="raise", viewonly=True)

    @property
    def extension(self) -> str:
        return self.file_name.rsplit(".", 1)[-1].lower() if "." in self.file_name else ""

    def __repr__(self) -> str:
        return f"<DocumentFile id={self.id} doc={self.document_id} {self.page_side} {self.file_name!r}>"


class DocumentLink(
    BigIntPKWithUUIDMixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """Polymorphic pivot: what a logical document belongs to, and in what role.

    Attaching is the INSERT (``created_at`` / ``created_by``); detaching is the
    soft delete (``deleted_at`` / ``deleted_by`` / ``deleted_reason``) — there are
    no separate attach/detach columns to keep in step.
    """

    __tablename__ = "document_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="fk_document_links_tenant_document", ondelete="CASCADE",
        ),
        CheckConstraint(f"link_role IN ({values(DocumentLinkRole)})", name="chk_document_link_role"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="chk_document_link_status"),
        CheckConstraint("linkable_id > 0", name="chk_document_link_linkable_id"),
        # linkable_type is deliberately open (no CHECK): a new owner class needs no migration.
        # THE read path: "all documents of user X" (the KYC completeness join).
        Index("ix_document_links_linkable", "tenant_id", "linkable_type", "linkable_id",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_document_links_document", "document_id", postgresql_where=text("deleted_at IS NULL")),
        Index("uq_document_links_dedupe", "document_id", "linkable_type", "linkable_id", "link_role",
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        # At most ONE owner link per logical document (the KYC subject).
        Index("uq_document_links_one_owner", "document_id", unique=True,
              postgresql_where=text("link_role = 'owner' AND deleted_at IS NULL")),
        {"comment": "Polymorphic pivot: any entity <-> a logical document, with a role."},
    )

    document_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The logical document (composite FK with tenant_id)",
    )
    linkable_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="WHO: snake_case owner class — user / vehicle / email / …",
    )
    linkable_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The linked entity's internal id (resolve with linkable_type)",
    )
    link_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentLinkRole.OWNER.value,
        server_default=text(f"'{DocumentLinkRole.OWNER.value}'"),
        comment="WHAT KIND: owner / attachment / evidence / reference / version_of",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Primary link among several of the same role",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="Ordering hint within a role",
    )
    context: Mapped[dict | None] = mapped_column(
        JSONB, comment="Per-link display hints (badge_label, tile_hint; for email: is_inline / content_id)",
    )

    document: Mapped[Document] = relationship(back_populates="links", lazy="raise", viewonly=True)

    def __repr__(self) -> str:
        return f"<DocumentLink doc={self.document_id} {self.linkable_type}:{self.linkable_id} {self.link_role}>"


class DocumentVerificationLog(IntPKMixin, LedgerMixin, Base):
    """Immutable, append-only trail of every status transition of a document.

    A LEDGER table: no ``row_version``, no soft delete — an audit trail is never
    "deleted". The FK to ``documents`` is RESTRICT (the reference design cascades):
    purging a document must be a deliberate act that decides what happens to its
    trail. At scale, range-partition monthly on ``performed_at``.
    """

    __tablename__ = "document_verification_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="fk_document_logs_tenant_document", ondelete="RESTRICT",
        ),
        CheckConstraint(f"action IN ({values(DocumentAuditAction)})", name="chk_document_log_action"),
        CheckConstraint(f"actor_type IN ({values(VerificationActorType)})", name="chk_document_log_actor_type"),
        CheckConstraint(f"previous_status IS NULL OR previous_status IN ({values(DocumentVerificationStatus)})",
                        name="chk_document_log_previous_status"),
        CheckConstraint(f"new_status IS NULL OR new_status IN ({values(DocumentVerificationStatus)})",
                        name="chk_document_log_new_status"),
        Index("ix_document_logs_document", "document_id", "performed_at"),
        Index("ix_document_logs_tenant", "tenant_id", "performed_at"),
        Index("ix_document_logs_primary_link", "tenant_id", "primary_link_type", "primary_link_id"),
        {"comment": "Append-only audit trail of document status transitions."},
    )

    document_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The document whose status transitioned (composite FK with tenant_id)",
    )
    # Snapshot of the document's owner link at transition time — immutable.
    primary_link_type: Mapped[str | None] = mapped_column(String(50), comment="Snapshot of the owner's linkable_type")
    primary_link_id: Mapped[int | None] = mapped_column(BigInteger, comment="Snapshot of the owner's linkable_id")
    action: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="uploaded / resubmitted / in_review / verified / rejected / resubmission_requested / "
                "expired / deleted / downloaded",
    )
    previous_status: Mapped[str | None] = mapped_column(String(30), comment="Status before the transition")
    new_status: Mapped[str | None] = mapped_column(String(30), comment="Status after the transition")
    actor_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=VerificationActorType.STAFF.value,
        server_default=text(f"'{VerificationActorType.STAFF.value}'"), comment="staff / system / third_party_webhook",
    )
    performed_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id of the actor (NULL = system)")
    performed_by_name: Mapped[str | None] = mapped_column(
        String(255), comment="Actor display name at the time (survives the user being erased)",
    )
    performed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
        comment="When the transition occurred",
    )
    remarks: Mapped[str | None] = mapped_column(Text, comment="Free-form notes on the transition")
    ip_address: Mapped[str | None] = mapped_column(String(45), comment="IP address of the actor")
    device_info: Mapped[str | None] = mapped_column(String(255), comment="Device information of the actor")

    def __repr__(self) -> str:
        return f"<DocumentVerificationLog doc={self.document_id} {self.action} {self.previous_status}->{self.new_status}>"
