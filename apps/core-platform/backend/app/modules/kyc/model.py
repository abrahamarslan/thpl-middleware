"""KYC / verification models.

KYC is modelled as a *cycle*: ``KYCProfile`` gets a new row per run (initial,
periodic re-KYC, triggered re-KYC, address update) and ``is_current`` marks the
active one. Identity details hang off the cycle.

Aadhaar: ``AadhaarVerification`` NEVER stores the 12-digit number. It keeps the
UIDAI masked form (last 4), an opaque pointer into the external Aadhaar Data
Vault, and the UID token. Demographics returned by e-KYC are stored locally but
the UID token is isolated (a sibling row / the vault) per UIDAI guidance.

Police verification is a ``BackgroundVerification`` of type
``police_verification_certificate`` — one table, not two.
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
from app.database.mixins import IntPKMixin, OrgEntityMixin, VerificationMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.compliance.mixins import ConsentBoundMixin
from app.modules.kyc.enums import (
    AadhaarVerificationMethod,
    BGVCheckStatus,
    BGVStatus,
    BGVType,
    KYCStatus,
    KYCType,
    KYCRiskLevel,
    MedicalCertificateStatus,
    MedicalCertificateType,
    PANType,
    PANVerificationSource,
    SubVerificationStatus,
    TrainingStatus,
    TrainingType,
    values,
)


def _sub_status_check(name: str, column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN ({values(SubVerificationStatus)})", name=name)


class KYCProfile(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One KYC cycle for one user. History table — filter on ``is_current``."""

    __tablename__ = "kyc_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_kyc_profiles_tenant_org_id"),
        UniqueConstraint("tenant_id", "id", name="uq_kyc_profiles_tenant_id"),
        UniqueConstraint("tenant_id", "user_id", "kyc_cycle_number", name="uq_kyc_profiles_user_cycle"),
        # Invariant: at most one CURRENT KYC cycle per user.
        Index("uq_kyc_profiles_one_current", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_current AND deleted_at IS NULL")),
        Index("ix_kyc_profiles_user_current", "tenant_id", "user_id", "is_current",
              postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint(f"kyc_type IN ({values(KYCType)})", name="chk_kyc_profile_type"),
        CheckConstraint(f"status IN ({values(KYCStatus)})", name="chk_kyc_profile_status"),
        CheckConstraint("risk_level IS NULL OR risk_level IN "
                        f"({values(KYCRiskLevel)})", name="chk_kyc_profile_risk"),
        CheckConstraint("kyc_cycle_number >= 1", name="chk_kyc_profile_cycle_number"),
        CheckConstraint("name_match_score IS NULL OR (name_match_score >= 0 AND name_match_score <= 100)",
                        name="chk_kyc_profile_name_score"),
        CheckConstraint("face_match_score IS NULL OR (face_match_score >= 0 AND face_match_score <= 100)",
                        name="chk_kyc_profile_face_score"),
        _sub_status_check("chk_kyc_identity_status", "identity_verification_status"),
        _sub_status_check("chk_kyc_address_status", "address_verification_status"),
        _sub_status_check("chk_kyc_age_status", "age_verification_status"),
        _sub_status_check("chk_kyc_name_match_status", "name_match_status"),
        _sub_status_check("chk_kyc_face_match_status", "face_match_status"),
        {"comment": "KYC cycles — one row per run, is_current marks the active one."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kyc_cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kyc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=KYCStatus.NOT_STARTED.value,
        server_default=text(f"'{KYCStatus.NOT_STARTED.value}'"), index=True,
    )
    risk_level: Mapped[str | None] = mapped_column(String(10))

    initiated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    identity_verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    address_verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    age_verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    name_match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    name_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    face_match_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    face_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    kyc_provider: Mapped[str | None] = mapped_column(String(100))
    kyc_provider_reference_id: Mapped[str | None] = mapped_column(String(255))

    reviewed_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)

    aadhaar_verification: Mapped["AadhaarVerification | None"] = relationship(
        back_populates="kyc_profile", uselist=False, lazy="raise",
    )
    pan_verification: Mapped["PANVerification | None"] = relationship(
        back_populates="kyc_profile", uselist=False, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<KYCProfile id={self.id} user={self.user_id} cycle={self.kyc_cycle_number} {self.status}>"


class AadhaarVerification(IntPKMixin, OrgEntityMixin, ConsentBoundMixin, SoftDeleteFilteredMixin, Base):
    """UIDAI-ADV-compliant Aadhaar verification. Never the raw 12-digit number."""

    __tablename__ = "aadhaar_verifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_aadhaar_verifications_tenant_org_id"),
        ForeignKeyConstraint(
            ["tenant_id", "kyc_profile_id"], ["kyc_profiles.tenant_id", "kyc_profiles.id"],
            name="fk_aadhaar_verifications_kyc_profile", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "kyc_profile_id", name="uq_aadhaar_verifications_cycle"),
        CheckConstraint(f"verification_method IN ({values(AadhaarVerificationMethod)})",
                        name="chk_aadhaar_method"),
        _sub_status_check("chk_aadhaar_status", "verification_status"),
        {"comment": "ADV-isolated Aadhaar verification (masked + vault reference only)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kyc_profile_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    masked_aadhaar_number: Mapped[str | None] = mapped_column(String(20), comment="UIDAI masked form XXXX XXXX 1234")
    aadhaar_vault_reference_key: Mapped[str | None] = mapped_column(
        String(255), index=True, comment="Opaque pointer into the external Aadhaar Data Vault",
    )
    uid_token: Mapped[str | None] = mapped_column(
        String(255), comment="UIDAI UID Token (required); isolate from demographics per UIDAI guidance",
    )
    verification_method: Mapped[str] = mapped_column(String(30), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    verification_reference_id: Mapped[str | None] = mapped_column(String(255))
    verified_name: Mapped[str | None] = mapped_column(String(255))
    verified_dob: Mapped[dt.date | None] = mapped_column(Date)
    verified_gender: Mapped[str | None] = mapped_column(String(20))
    verified_address: Mapped[dict | None] = mapped_column(JSONB)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    kyc_profile: Mapped["KYCProfile"] = relationship(back_populates="aadhaar_verification", lazy="raise")

    def __repr__(self) -> str:
        return f"<AadhaarVerification id={self.id} user={self.user_id} {self.verification_status}>"


class PANVerification(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """PAN verification — full PAN only as app-layer ciphertext; masked for search."""

    __tablename__ = "pan_verifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_pan_verifications_tenant_org_id"),
        ForeignKeyConstraint(
            ["tenant_id", "kyc_profile_id"], ["kyc_profiles.tenant_id", "kyc_profiles.id"],
            name="fk_pan_verifications_kyc_profile", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "kyc_profile_id", name="uq_pan_verifications_cycle"),
        CheckConstraint(f"pan_type IN ({values(PANType)})", name="chk_pan_type"),
        CheckConstraint("verification_source IS NULL OR verification_source IN "
                        f"({values(PANVerificationSource)})", name="chk_pan_source"),
        _sub_status_check("chk_pan_status", "verification_status"),
        Index("ix_pan_verifications_masked", "tenant_id", "pan_number_masked",
              postgresql_where=text("pan_number_masked IS NOT NULL AND deleted_at IS NULL")),
        {"comment": "PAN verification (encrypted + masked)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kyc_profile_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pan_number_masked: Mapped[str | None] = mapped_column(String(12), comment="e.g. ABCDE****F")
    pan_number_encrypted: Mapped[str | None] = mapped_column(Text, comment="App-layer-encrypted full PAN")
    pan_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PANType.INDIVIDUAL.value,
        server_default=text(f"'{PANType.INDIVIDUAL.value}'"),
    )
    verification_source: Mapped[str | None] = mapped_column(String(40))
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubVerificationStatus.NOT_STARTED.value,
        server_default=text(f"'{SubVerificationStatus.NOT_STARTED.value}'"),
    )
    verified_name: Mapped[str | None] = mapped_column(String(255))
    name_match_with_aadhaar: Mapped[bool | None] = mapped_column(Boolean)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    kyc_profile: Mapped["KYCProfile"] = relationship(back_populates="pan_verification", lazy="raise")

    def __repr__(self) -> str:
        return f"<PANVerification id={self.id} user={self.user_id} {self.verification_status}>"


class LivenessVerification(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Selfie + liveness check + face-match against an identity document."""

    __tablename__ = "liveness_verifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_liveness_verifications_tenant_org_id"),
        CheckConstraint("face_match_score IS NULL OR (face_match_score >= 0 AND face_match_score <= 1)",
                        name="chk_liveness_face_score"),
        CheckConstraint("face_match_threshold IS NULL OR (face_match_threshold >= 0 AND face_match_threshold <= 1)",
                        name="chk_liveness_face_threshold"),
        Index("ix_liveness_verifications_user", "tenant_id", "user_id", text("captured_at DESC"),
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Selfie / liveness / face-match records."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    matched_against_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"),
    )
    selfie_storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    liveness_check_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    liveness_failure_reason: Mapped[str | None] = mapped_column(String(150))
    face_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    face_match_threshold: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    face_match_passed: Mapped[bool | None] = mapped_column(Boolean)
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_reference_id: Mapped[str | None] = mapped_column(String(150))
    provider_response: Mapped[dict | None] = mapped_column(JSONB)
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_geo_location_wkt: Mapped[str | None] = mapped_column(
        String(100), comment="WKT POINT; swap for Geography(POINT,4326) in production",
    )
    device_id: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    def __repr__(self) -> str:
        return f"<LivenessVerification id={self.id} user={self.user_id} passed={self.liveness_check_passed}>"


class BackgroundVerification(IntPKMixin, OrgEntityMixin, VerificationMixin, ConsentBoundMixin,
                             SoftDeleteFilteredMixin, Base):
    """One background-check run (PVC and/or third-party BGV agency check).

    Police verification is this table with
    ``bgv_type = police_verification_certificate``; the PVC-specific fields are
    used for that type. ``supersedes_id`` chains renewals.
    """

    __tablename__ = "background_verifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_background_verifications_tenant_org_id"),
        UniqueConstraint("tenant_id", "id", name="uq_background_verifications_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"], ["background_verifications.tenant_id", "background_verifications.id"],
            name="fk_background_verifications_supersedes", ondelete="SET NULL",
        ),
        CheckConstraint(f"bgv_type IN ({values(BGVType)})", name="chk_bgv_type"),
        CheckConstraint(f"status IN ({values(BGVStatus)})", name="chk_bgv_status"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="chk_bgv_not_own_predecessor"),
        Index("ix_background_verifications_user_status", "tenant_id", "user_id", "status",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_background_verifications_due", "next_review_due_at",
              postgresql_where=text("next_review_due_at IS NOT NULL AND deleted_at IS NULL")),
        {"comment": "Background-verification runs (incl. police verification / PVC)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    bgv_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=BGVStatus.NOT_INITIATED.value,
        server_default=text(f"'{BGVStatus.NOT_INITIATED.value}'"), index=True,
    )
    vendor_name: Mapped[str | None] = mapped_column(String(100))
    vendor_reference_id: Mapped[str | None] = mapped_column(String(255))

    # --- police verification certificate specific ---
    police_station_jurisdiction: Mapped[str | None] = mapped_column(String(255))
    pvc_certificate_number: Mapped[str | None] = mapped_column(String(100))
    pvc_issued_date: Mapped[dt.date | None] = mapped_column(Date)
    pvc_valid_upto: Mapped[dt.date | None] = mapped_column(Date)

    initiated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str | None] = mapped_column(String(255))
    adverse_finding_summary: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_due_at: Mapped[dt.date | None] = mapped_column(Date)
    supersedes_id: Mapped[int | None] = mapped_column(BigInteger, comment="Previous run/certificate this replaces")

    check_results: Mapped[list["BGVCheckResult"]] = relationship(
        back_populates="bgv", lazy="selectin", order_by="BGVCheckResult.id",
    )

    def __repr__(self) -> str:
        return f"<BackgroundVerification id={self.id} user={self.user_id} {self.bgv_type}/{self.status}>"


class BGVCheckResult(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One sub-check within a BGV run (normalized: new check types are rows)."""

    __tablename__ = "bgv_check_results"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_bgv_check_results_tenant_org_id"),
        ForeignKeyConstraint(
            ["tenant_id", "bgv_id"], ["background_verifications.tenant_id", "background_verifications.id"],
            name="fk_bgv_check_results_bgv", ondelete="CASCADE",
        ),
        CheckConstraint(f"status IN ({values(BGVCheckStatus)})", name="chk_bgv_check_status"),
        Index("ix_bgv_check_results_bgv_status", "bgv_id", "status", postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Normalized sub-checks of a BGV run."},
    )

    bgv_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    check_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="criminal / address / employment_history / education / reference",
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=BGVCheckStatus.PENDING.value,
        server_default=text(f"'{BGVCheckStatus.PENDING.value}'"), index=True,
    )
    details: Mapped[dict | None] = mapped_column(JSONB)
    provider_reference_id: Mapped[str | None] = mapped_column(String(255))
    verified_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    bgv: Mapped["BackgroundVerification"] = relationship(back_populates="check_results", lazy="raise")

    def __repr__(self) -> str:
        return f"<BGVCheckResult id={self.id} bgv={self.bgv_id} {self.check_type}/{self.status}>"


class MedicalFitnessCertificate(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Driving/general medical-fitness certificate for a user."""

    __tablename__ = "medical_fitness_certificates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_medical_fitness_tenant_org_id"),
        CheckConstraint(f"certificate_type IN ({values(MedicalCertificateType)})", name="chk_medical_cert_type"),
        CheckConstraint(f"status IN ({values(MedicalCertificateStatus)})", name="chk_medical_cert_status"),
        CheckConstraint("valid_upto IS NULL OR issued_date IS NULL OR valid_upto >= issued_date",
                        name="chk_medical_cert_dates"),
        Index("ix_medical_fitness_user", "tenant_id", "user_id", postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Medical fitness certificates (MoRTH Form 1A / general / eye)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    certificate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    issued_by_doctor_name: Mapped[str | None] = mapped_column(String(255))
    issuing_hospital_clinic: Mapped[str | None] = mapped_column(String(255))
    issued_date: Mapped[dt.date | None] = mapped_column(Date)
    valid_upto: Mapped[dt.date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MedicalCertificateStatus.VALID.value,
        server_default=text(f"'{MedicalCertificateStatus.VALID.value}'"),
    )
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))

    def __repr__(self) -> str:
        return f"<MedicalFitnessCertificate id={self.id} user={self.user_id} {self.certificate_type}>"


class TrainingCertification(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A completed training / certification for a user."""

    __tablename__ = "training_certifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_training_certifications_tenant_org_id"),
        CheckConstraint(f"training_type IN ({values(TrainingType)})", name="chk_training_type"),
        CheckConstraint(f"status IN ({values(TrainingStatus)})", name="chk_training_status"),
        CheckConstraint("score_percentage IS NULL OR (score_percentage >= 0 AND score_percentage <= 100)",
                        name="chk_training_score"),
        Index("ix_training_certifications_user", "tenant_id", "user_id", postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Training / certification completions."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    training_type: Mapped[str] = mapped_column(String(40), nullable=False)
    training_provider: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TrainingStatus.NOT_STARTED.value,
        server_default=text(f"'{TrainingStatus.NOT_STARTED.value}'"),
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    score_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valid_upto: Mapped[dt.date | None] = mapped_column(Date)
    certificate_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"),
    )

    def __repr__(self) -> str:
        return f"<TrainingCertification id={self.id} user={self.user_id} {self.training_type}/{self.status}>"
