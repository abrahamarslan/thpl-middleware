"""Compliance models — DPDP Act, 2023 records.

    consent_records            ENTITY   explicit consent ledger
    data_retention_schedules   GLOBAL   per-category retention rules
    data_principal_requests    ENTITY   rights lifecycle + SLA
    kyc_audit_logs             LEDGER   immutable before/after compliance trail
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    DeactivationMixin,
    IntPKMixin,
    MultiTenantMixin,
    OrgEntityMixin,
    RowVersionMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.compliance.enums import (
    ConsentChannel,
    ConsentType,
    DataPrincipalRequestStatus,
    DataPrincipalRequestType,
    RetentionAction,
    values,
)


class ConsentRecord(
    IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """Explicit consent record required under the DPDP Act, 2023.

    The single source of truth for consent across every consent-worthy purpose
    (Aadhaar eKYC, biometric capture, BGV/police verification, location
    tracking, third-party sharing, marketing). Consent-worthy rows link here
    through ``ConsentBoundMixin.consent_id``.
    """

    __tablename__ = "consent_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_consent_records_tenant_org_id"),
        CheckConstraint(f"consent_type IN ({values(ConsentType)})", name="chk_consent_type"),
        CheckConstraint(f"consent_channel IN ({values(ConsentChannel)})", name="chk_consent_channel"),
        CheckConstraint("withdrawn_at IS NULL OR withdrawn_at >= consented_at", name="chk_consent_withdrawal"),
        Index("ix_consent_records_user_type", "tenant_id", "user_id", "consent_type",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_consent_records_active", "tenant_id", "user_id", "is_active",
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "DPDP consent ledger — single source of truth for consent."},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="The user who gave/withdrew consent",
    )
    consent_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="What processing was consented to")
    consent_given: Mapped[bool] = mapped_column(
        Boolean, nullable=False, comment="True = given; False = denied/withdrawn",
    )
    consent_text_version: Mapped[str | None] = mapped_column(String(20), comment="Version of the consent copy shown")
    consent_language: Mapped[str | None] = mapped_column(String(20), comment="Language the notice was shown in")
    purpose_text: Mapped[str | None] = mapped_column(String(255), comment="Specific purpose, human-readable")
    legal_basis_reference: Mapped[str | None] = mapped_column(Text, comment="e.g. 'DPDP Act 2023 s.6'")
    consent_channel: Mapped[str] = mapped_column(String(20), nullable=False, comment="mobile_app / web_portal / paper_form")
    consented_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_ip_address: Mapped[str | None] = mapped_column(String(45))
    consent_device_info: Mapped[dict | None] = mapped_column(JSONB)
    withdrawal_requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="False once withdrawn/superseded",
    )

    def __repr__(self) -> str:
        return f"<ConsentRecord id={self.id} user={self.user_id} type={self.consent_type!r} active={self.is_active}>"


class DataRetentionSchedule(
    IntPKMixin, AuditMixin, RowVersionMixin, AppMetaMixin, TimestampMixin, DeactivationMixin, Base,
):
    """Reference table: how long each data category may be retained, from what
    trigger, and what the purge job does once the period lapses.

    GLOBAL reference data (like ``document_types`` / ``countries``): every
    tenant reads the same rules. This is the application's data-retention rule
    table and is unrelated to Zoho payload retention policies.
    """

    __tablename__ = "data_retention_schedules"
    __table_args__ = (
        CheckConstraint(f"action IN ({values(RetentionAction)})", name="chk_retention_action"),
        CheckConstraint("retention_period_days > 0", name="chk_retention_period_positive"),
        CheckConstraint("grace_period_days >= 0", name="chk_retention_grace_nonnegative"),
        {"comment": "Per-category data-retention rules (global reference data)."},
    )

    data_category: Mapped[str] = mapped_column(
        String(60), unique=True, nullable=False, index=True,
        comment="e.g. aadhaar_document, pan_document, bgv_report, bank_details, location_history",
    )
    retention_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    retention_trigger_event: Mapped[str] = mapped_column(
        String(60), nullable=False, comment="e.g. employment_end_date, document_upload_date",
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RetentionAction.DELETE.value,
        server_default=text(f"'{RetentionAction.DELETE.value}'"), comment="delete / anonymize",
    )
    grace_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    legal_hold_exception: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    legal_basis: Mapped[str | None] = mapped_column(Text)
    auto_purge_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    last_reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
    )

    def __repr__(self) -> str:
        return f"<DataRetentionSchedule {self.data_category!r} {self.retention_period_days}d>"


class DataPrincipalRequest(
    IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """DPDP Act, 2023 data-principal rights request lifecycle with SLA tracking."""

    __tablename__ = "data_principal_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_data_principal_requests_tenant_org_id"),
        CheckConstraint(f"request_type IN ({values(DataPrincipalRequestType)})", name="chk_dpr_type"),
        CheckConstraint(f"status IN ({values(DataPrincipalRequestStatus)})", name="chk_dpr_status"),
        Index("ix_data_principal_requests_user_status", "tenant_id", "user_id", "status",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_data_principal_requests_sla", "sla_due_at", postgresql_where=text("sla_due_at IS NOT NULL")),
        {"comment": "DPDP data-principal rights requests with SLA tracking."},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="The data principal raising the request",
    )
    request_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="access / correction / erasure / grievance / nomination",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DataPrincipalRequestStatus.SUBMITTED.value,
        server_default=text(f"'{DataPrincipalRequestStatus.SUBMITTED.value}'"), index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, comment="What the data principal is asking for")
    submitted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sla_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<DataPrincipalRequest id={self.id} user={self.user_id} {self.request_type}/{self.status}>"


class KYCAuditLog(IntPKMixin, MultiTenantMixin, AppMetaMixin, Base):
    """Immutable schema-wide before/after audit trail of KYC/compliance events.

    The **compliance** ledger (distinct from ``activity_logs``, the operational
    and authentication trail). ``entity_type`` is an open String treated as
    data; ``AuditEntityType`` is the starter vocabulary. Append-only: no
    ``row_version``, no soft delete. At scale, range-partition monthly on
    ``performed_at`` (pg_partman), pairing with ``data_retention_schedules``.
    """

    __tablename__ = "kyc_audit_logs"
    __table_args__ = (
        Index("ix_kyc_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_kyc_audit_logs_user_time", "tenant_id", "user_id", text("performed_at DESC")),
        Index("ix_kyc_audit_logs_time", "tenant_id", text("performed_at DESC")),
        {"comment": "Append-only compliance audit trail (before/after snapshots)."},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="The user whose record was changed",
    )
    entity_type: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True,
        comment="Entity type — open vocabulary treated as data (see AuditEntityType)",
    )
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="PK of the entity changed")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="Verb: created/verified/rejected/…")
    performed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), comment="Actor; null for system/batch",
    )
    performed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB, comment="Snapshot before the change")
    new_value: Mapped[dict | None] = mapped_column(JSONB, comment="Snapshot after the change")
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    remarks: Mapped[str | None] = mapped_column(String(500))

    def __repr__(self) -> str:
        return f"<KYCAuditLog id={self.id} {self.entity_type}:{self.entity_id} {self.action}>"
