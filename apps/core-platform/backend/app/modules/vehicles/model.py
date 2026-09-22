"""Vehicle models.

The MVA six-document set (RC, Insurance, Fitness, PUC, Road Tax, Permit) plus
VLTD / speed-governor / HSRP are rows in ``vehicle_compliance_documents``, each
a renewal chain via ``renewed_from_id``. ``DrivingLicense`` holds the regulated,
structured DL facts (classes, commercial endorsement, Parivahan verification).

Two orthogonal axes are kept apart: the *scan's* verification lives on the
linked ``Document`` (``VerificationMixin`` + ``document_verification_logs``);
the *certificate's validity* is ``VehicleComplianceDocument.status``.
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
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    OrgEntityMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.enums import DocumentVerificationMethod
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.kyc.enums import SubVerificationStatus
from app.modules.vehicles.enums import (
    ComplianceDocStatus,
    FuelType,
    InsuranceType,
    PermitType,
    VehicleComplianceType,
    VehicleOwnershipType,
    VehicleStatus,
    VehicleType,
    values,
)


class Vehicle(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, HasDocumentsMixin, Base,
):
    """A physical vehicle in the fleet (owned or company/vendor-supplied)."""

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_vehicles_tenant_org_id"),
        UniqueConstraint("tenant_id", "id", name="uq_vehicles_tenant_id"),
        CheckConstraint(f"vehicle_type IN ({values(VehicleType)})", name="chk_vehicle_type"),
        CheckConstraint(f"ownership_type IN ({values(VehicleOwnershipType)})", name="chk_vehicle_ownership"),
        CheckConstraint(f"fuel_type IS NULL OR fuel_type IN ({values(FuelType)})", name="chk_vehicle_fuel"),
        CheckConstraint(f"status IN ({values(VehicleStatus)})", name="chk_vehicle_status"),
        CheckConstraint("manufacture_year IS NULL OR manufacture_year BETWEEN 1900 AND 2100",
                        name="chk_vehicle_year"),
        CheckConstraint("load_capacity_kg IS NULL OR load_capacity_kg >= 0", name="chk_vehicle_load"),
        CheckConstraint("seating_capacity IS NULL OR seating_capacity >= 0", name="chk_vehicle_seating"),
        CheckConstraint("battery_capacity_kwh IS NULL OR battery_capacity_kwh > 0", name="chk_vehicle_battery"),
        Index("uq_vehicles_registration_live", "tenant_id", "registration_number", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("uq_vehicles_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_vehicles_owner", "tenant_id", "owner_user_id", postgresql_where=text("owner_user_id IS NOT NULL")),
        Index("ix_vehicles_fleet_partner", "tenant_id", "fleet_partner_id",
              postgresql_where=text("fleet_partner_id IS NOT NULL")),
        Index("ix_vehicles_hub", "tenant_id", "hub_id", postgresql_where=text("hub_id IS NOT NULL")),
        Index("ix_vehicles_type_status", "tenant_id", "organization_id", "vehicle_type", "status",
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Fleet vehicle master (status/deactivation/verification from mixins)."},
    )

    registration_number: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Normalized uppercase, no spaces",
    )
    chassis_number: Mapped[str | None] = mapped_column(String(50), comment="Chassis / VIN")
    engine_number: Mapped[str | None] = mapped_column(String(50), comment="Engine / motor number")
    make: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    manufacture_year: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(50))
    load_capacity_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    seating_capacity: Mapped[int | None] = mapped_column(Integer)

    vehicle_type: Mapped[str] = mapped_column(String(30), nullable=False)
    ownership_type: Mapped[str] = mapped_column(String(30), nullable=False)
    fuel_type: Mapped[str | None] = mapped_column(String(20))
    battery_capacity_kwh: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), comment="EV only")

    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"),
        comment="DA/driver who owns & operates it; null for pooled company vehicles",
    )
    fleet_partner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fleet_partners.id", ondelete="SET NULL"),
    )
    hub_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("hubs.id", ondelete="SET NULL"))
    registered_owner_name: Mapped[str | None] = mapped_column(
        String(150), comment="RC owner when it differs from the app user; pair with VEHICLE_OWNER_NOC",
    )

    vltd_device_id: Mapped[str | None] = mapped_column(String(100))
    gps_device_id: Mapped[str | None] = mapped_column(String(100))
    fastag_id: Mapped[str | None] = mapped_column(String(50))
    is_company_fleet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    rc_status_cache: Mapped[str | None] = mapped_column(
        String(20), comment="CACHE of the latest RC compliance row's status",
    )
    overall_compliance_status_cache: Mapped[str | None] = mapped_column(
        String(20), comment="CACHE: valid only if ALL applicable compliance docs are VALID",
    )
    zoho_id: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    compliance_documents: Mapped[list["VehicleComplianceDocument"]] = relationship(
        back_populates="vehicle", lazy="selectin",
        order_by="VehicleComplianceDocument.valid_upto.desc().nullslast()",
    )

    def __repr__(self) -> str:
        return f"<Vehicle id={self.id} reg={self.registration_number!r} status={self.status!r}>"


class VehicleComplianceDocument(
    BigIntPKWithUUIDMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """One regulatory certificate for one vehicle, forming a renewal chain."""

    __tablename__ = "vehicle_compliance_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_vehicle_compliance_tenant_org_id"),
        UniqueConstraint("tenant_id", "id", name="uq_vehicle_compliance_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "vehicle_id"], ["vehicles.tenant_id", "vehicles.id"],
            name="fk_vehicle_compliance_vehicle", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "renewed_from_id"],
            ["vehicle_compliance_documents.tenant_id", "vehicle_compliance_documents.id"],
            name="fk_vehicle_compliance_renewed_from", ondelete="SET NULL",
        ),
        CheckConstraint(f"compliance_type IN ({values(VehicleComplianceType)})", name="chk_vehicle_compliance_type"),
        CheckConstraint(f"status IN ({values(ComplianceDocStatus)})", name="chk_vehicle_compliance_status"),
        CheckConstraint("insurance_type IS NULL OR insurance_type IN "
                        f"({values(InsuranceType)})", name="chk_vehicle_compliance_insurance"),
        CheckConstraint("permit_type IS NULL OR permit_type IN "
                        f"({values(PermitType)})", name="chk_vehicle_compliance_permit"),
        CheckConstraint("valid_upto IS NULL OR valid_from IS NULL OR valid_upto >= valid_from",
                        name="chk_vehicle_compliance_validity"),
        CheckConstraint("renewed_from_id IS NULL OR renewed_from_id <> id",
                        name="chk_vehicle_compliance_not_own_predecessor"),
        Index("ix_vehicle_compliance_vehicle_type_status", "vehicle_id", "compliance_type", "status",
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_vehicle_compliance_expiry", "valid_upto",
              postgresql_where=text("valid_upto IS NOT NULL AND deleted_at IS NULL")),
        {"comment": "Per-certificate vehicle compliance records (renewal chain)."},
    )

    vehicle_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"),
        comment="The uploaded scan of this certificate",
    )
    compliance_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    certificate_number: Mapped[str | None] = mapped_column(String(100))
    insurer_name: Mapped[str | None] = mapped_column(String(255))
    insurance_type: Mapped[str | None] = mapped_column(String(20))
    permit_type: Mapped[str | None] = mapped_column(String(40))
    permit_region: Mapped[str | None] = mapped_column(String(100))
    issued_date: Mapped[dt.date | None] = mapped_column(Date)
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_upto: Mapped[dt.date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ComplianceDocStatus.PENDING_RENEWAL.value,
        server_default=text(f"'{ComplianceDocStatus.PENDING_RENEWAL.value}'"), index=True,
    )
    renewal_reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    renewed_from_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The certificate this one renews (composite FK with tenant_id)",
    )

    vehicle: Mapped["Vehicle"] = relationship(back_populates="compliance_documents", lazy="raise")

    def __repr__(self) -> str:
        return f"<VehicleComplianceDocument id={self.id} vehicle={self.vehicle_id} {self.compliance_type}/{self.status}>"


class DrivingLicense(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, SoftDeleteFilteredMixin, Base,
):
    """One DL version per user; at most one current (partial unique)."""

    __tablename__ = "driving_licenses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_driving_licenses_tenant_org_id"),
        Index("uq_driving_licenses_one_current", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_current AND deleted_at IS NULL")),
        Index("ix_driving_licenses_user", "tenant_id", "user_id", postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("valid_upto >= valid_from", name="chk_dl_validity"),
        CheckConstraint(f"verification_status IN ({values(SubVerificationStatus)})", name="chk_dl_verification"),
        CheckConstraint("verification_method IS NULL OR verification_method IN "
                        f"({values(DocumentVerificationMethod)})", name="chk_dl_verification_method"),
        {"comment": "Driving licenses — structured DL facts (history, is_current)."},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="SET NULL"))
    dl_number_masked: Mapped[str | None] = mapped_column(String(30), comment="e.g. GJ01 XXXXXXX1234")
    dl_number_encrypted: Mapped[str | None] = mapped_column(Text, comment="App-layer-encrypted full DL number")
    dl_classes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
        comment='e.g. ["MCWG", "LMV", "LMV-TR"]',
    )
    issuing_rto: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[dt.date | None] = mapped_column(Date)
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_upto: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    is_commercial_license: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Transport/commercial endorsement (MVA s.3)",
    )
    badge_number: Mapped[str | None] = mapped_column(String(50))
    badge_issuing_authority: Mapped[str | None] = mapped_column(String(150))
    badge_valid_upto: Mapped[dt.date | None] = mapped_column(Date)

    # Overrides VerificationMixin.verification_status: the DL vocabulary.
    verification_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=SubVerificationStatus.PENDING.value,
        server_default=text(f"'{SubVerificationStatus.PENDING.value}'"), index=True,
    )
    verified_via_parivahan: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    parivahan_reference_id: Mapped[str | None] = mapped_column(String(150))
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )

    def __repr__(self) -> str:
        return f"<DrivingLicense id={self.id} user={self.user_id} current={self.is_current}>"
