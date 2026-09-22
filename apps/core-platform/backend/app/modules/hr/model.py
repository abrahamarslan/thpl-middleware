"""HR / employment models.

Employment is a history table (exit + rejoin), not a 1:1 profile — use
``is_current`` to find the active stint. Gig-worker statutory registration
(Code on Social Security, 2020 / e-Shram) is 1:1; the running eligibility
accrual is per financial year. Payout bank accounts are payee-polymorphic so a
fleet partner can hold one too.
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
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    IntPKMixin,
    OrgEntityMixin,
    PolymorphicOwnerMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.hr.enums import (
    AggregatorSyncStatus,
    BankAccountOwnerType,
    BankAccountType,
    BankVerificationMethod,
    BankVerificationStatus,
    EmploymentStatus,
    EmploymentType,
    EshramRegistrationStatus,
    GigBenefitEligibilityStatus,
    PersonnelType,
    WorkLocationType,
    WorkerCategory,
    values,
)

_OWNER_TYPE_SQL = values(BankAccountOwnerType)


class EmploymentRecord(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One employment 'stint' for a user. History table — filter on is_current."""

    __tablename__ = "employment_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_employment_records_tenant_org_id"),
        # Invariant: at most one CURRENT stint per user.
        Index("uq_employment_records_one_current", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_current AND deleted_at IS NULL")),
        Index("ix_employment_records_user_current", "tenant_id", "user_id", "is_current",
              postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint(f"personnel_type IN ({values(PersonnelType)})", name="chk_employment_personnel_type"),
        CheckConstraint(f"employment_type IN ({values(EmploymentType)})", name="chk_employment_type"),
        CheckConstraint(f"employment_status IN ({values(EmploymentStatus)})", name="chk_employment_status"),
        CheckConstraint("work_location_type IS NULL OR work_location_type IN "
                        f"({values(WorkLocationType)})", name="chk_employment_work_location"),
        CheckConstraint("date_of_exit IS NULL OR date_of_exit >= date_of_joining", name="chk_employment_dates"),
        Index("uq_employment_records_employee_code", "tenant_id", "employee_code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Employment stints (history); is_current marks the active one."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    employee_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="THPL-internal employee/DA code, e.g. THPL-GDH-DA-00231",
    )
    hrms_id: Mapped[str | None] = mapped_column(String(100), index=True)
    erp_id: Mapped[str | None] = mapped_column(String(100), index=True)
    zoho_people_id: Mapped[str | None] = mapped_column(String(100))
    biometric_enrollment_id: Mapped[str | None] = mapped_column(String(100))

    personnel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    employment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    employment_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=EmploymentStatus.PENDING_ONBOARDING.value,
        server_default=text(f"'{EmploymentStatus.PENDING_ONBOARDING.value}'"),
    )
    work_location_type: Mapped[str | None] = mapped_column(String(20))
    department: Mapped[str | None] = mapped_column(String(100))
    designation: Mapped[str | None] = mapped_column(String(100))
    cost_center: Mapped[str | None] = mapped_column(String(50))

    hub_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("hubs.id", ondelete="SET NULL"))
    reporting_manager_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
    )
    fleet_partner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fleet_partners.id", ondelete="SET NULL"),
    )

    date_of_joining: Mapped[dt.date] = mapped_column(Date, nullable=False)
    probation_period_days: Mapped[int | None] = mapped_column(Integer)
    date_of_confirmation: Mapped[dt.date | None] = mapped_column(Date)
    notice_period_days: Mapped[int | None] = mapped_column(Integer)
    date_of_exit: Mapped[dt.date | None] = mapped_column(Date)
    exit_reason: Mapped[str | None] = mapped_column(String(255))
    rehire_eligible: Mapped[bool | None] = mapped_column(Boolean)

    epfo_uan: Mapped[str | None] = mapped_column(String(20), comment="EPFO UAN (on-roll)")
    esic_number: Mapped[str | None] = mapped_column(String(20), comment="ESIC number (on-roll)")
    professional_tax_state: Mapped[str | None] = mapped_column(String(100))
    bank_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bank_accounts.id", ondelete="SET NULL"),
    )

    def __repr__(self) -> str:
        return f"<EmploymentRecord id={self.id} user={self.user_id} code={self.employee_code!r}>"


class GigWorkerRegistration(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Code on Social Security, 2020 / e-Shram compliance — one row per user."""

    __tablename__ = "gig_worker_registrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_gig_worker_registrations_tenant_org_id"),
        UniqueConstraint("tenant_id", "user_id", name="uq_gig_worker_registrations_user"),
        CheckConstraint(f"worker_category IN ({values(WorkerCategory)})", name="chk_gig_worker_category"),
        CheckConstraint(f"eshram_registration_status IN ({values(EshramRegistrationStatus)})",
                        name="chk_gig_eshram_status"),
        CheckConstraint(f"aggregator_api_sync_status IN ({values(AggregatorSyncStatus)})",
                        name="chk_gig_aggregator_sync"),
        Index("uq_gig_worker_registrations_uan", "tenant_id", "eshram_uan", unique=True,
              postgresql_where=text("eshram_uan IS NOT NULL AND deleted_at IS NULL")),
        {"comment": "Gig/platform worker statutory registration (e-Shram)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    worker_category: Mapped[str] = mapped_column(String(30), nullable=False)

    eshram_uan: Mapped[str | None] = mapped_column(String(20), comment="e-Shram Universal Account Number")
    eshram_registration_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=EshramRegistrationStatus.NOT_REGISTERED.value,
        server_default=text(f"'{EshramRegistrationStatus.NOT_REGISTERED.value}'"),
    )
    eshram_registered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    eshram_card_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"),
    )
    aggregator_api_sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AggregatorSyncStatus.PENDING.value,
        server_default=text(f"'{AggregatorSyncStatus.PENDING.value}'"),
    )
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    welfare_fund_contribution_applicable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    days_worked_current_quarter: Mapped[int | None] = mapped_column(Integer)
    accident_insurance_provider: Mapped[str | None] = mapped_column(String(255))
    accident_insurance_policy_number: Mapped[str | None] = mapped_column(String(100))
    accident_insurance_valid_upto: Mapped[dt.date | None] = mapped_column(Date)
    health_insurance_provider: Mapped[str | None] = mapped_column(String(255))
    health_insurance_policy_number: Mapped[str | None] = mapped_column(String(100))
    health_insurance_valid_upto: Mapped[dt.date | None] = mapped_column(Date)

    def __repr__(self) -> str:
        return f"<GigWorkerRegistration id={self.id} user={self.user_id} {self.worker_category}>"


class GigWorkerFYStats(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Per-(worker, financial year) accrual for benefit-eligibility rules."""

    __tablename__ = "gig_worker_fy_stats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_gig_worker_fy_stats_tenant_org_id"),
        UniqueConstraint("tenant_id", "user_id", "financial_year", name="uq_gig_worker_fy_stats_user_fy"),
        CheckConstraint(f"benefit_eligibility_status IN ({values(GigBenefitEligibilityStatus)})",
                        name="chk_gig_fy_eligibility"),
        CheckConstraint("total_days_worked_fy >= 0", name="chk_gig_fy_days"),
        {"comment": "Gig-worker per-financial-year benefit-eligibility accrual."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    financial_year: Mapped[str] = mapped_column(String(9), nullable=False, index=True, comment='e.g. "2026-27"')
    total_days_worked_fy: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    is_multi_aggregator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    aggregate_90_day_met_at: Mapped[dt.date | None] = mapped_column(Date)
    aggregate_120_day_met_at: Mapped[dt.date | None] = mapped_column(Date)
    benefit_eligibility_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=GigBenefitEligibilityStatus.NOT_ELIGIBLE.value,
        server_default=text(f"'{GigBenefitEligibilityStatus.NOT_ELIGIBLE.value}'"), index=True,
    )
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<GigWorkerFYStats id={self.id} user={self.user_id} fy={self.financial_year!r}>"


class BankAccount(
    IntPKMixin, OrgEntityMixin, PolymorphicOwnerMixin, SoftDeleteFilteredMixin, Base,
):
    """A payout bank account for a user or a fleet partner.

    Only the last 4 digits are stored in plaintext; the full number lives as
    app-layer ciphertext decrypted only by the payout service.
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_bank_accounts_tenant_org_id"),
        CheckConstraint(f"owner_type IN ({_OWNER_TYPE_SQL})", name="chk_bank_account_owner_type"),
        CheckConstraint(f"account_type IS NULL OR account_type IN ({values(BankAccountType)})",
                        name="chk_bank_account_type"),
        CheckConstraint(f"verification_method IS NULL OR verification_method IN "
                        f"({values(BankVerificationMethod)})", name="chk_bank_account_method"),
        CheckConstraint(f"verification_status IN ({values(BankVerificationStatus)})",
                        name="chk_bank_account_status"),
        CheckConstraint("name_match_score IS NULL OR (name_match_score >= 0 AND name_match_score <= 100)",
                        name="chk_bank_account_name_score"),
        # Practical dedupe on retry (NULLs are distinct in PG).
        Index("uq_bank_accounts_owner_ifsc_last4", "tenant_id", "owner_type", "owner_id",
              "ifsc_code", "account_number_last4", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        # At most one PRIMARY payout account per payee.
        Index("uq_bank_accounts_one_primary", "tenant_id", "owner_type", "owner_id", unique=True,
              postgresql_where=text("is_primary AND is_active AND deleted_at IS NULL")),
        # THE read path: "this payee's accounts".
        Index("ix_bank_accounts_owner", "tenant_id", "owner_type", "owner_id",
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Payee-polymorphic payout bank accounts (user | fleet_partner)."},
    )

    account_holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number_encrypted: Mapped[str | None] = mapped_column(
        String(512), comment="App-layer-encrypted ciphertext; never queried directly",
    )
    account_number_last4: Mapped[str | None] = mapped_column(String(4), comment="Last 4 digits for display/search")
    ifsc_code: Mapped[str | None] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(String(255))
    branch_name: Mapped[str | None] = mapped_column(String(255))
    account_type: Mapped[str | None] = mapped_column(String(20))
    upi_vpa: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deactivated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    verification_method: Mapped[str | None] = mapped_column(String(30))
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=BankVerificationStatus.PENDING.value,
        server_default=text(f"'{BankVerificationStatus.PENDING.value}'"),
    )
    penny_drop_reference_id: Mapped[str | None] = mapped_column(String(255))
    name_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))

    def __repr__(self) -> str:
        return f"<BankAccount id={self.id} {self.owner_type}:{self.owner_id} ****{self.account_number_last4}>"
