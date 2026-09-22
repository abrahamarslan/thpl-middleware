"""Transport schemas for the vehicle module."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.vehicles.enums import (
    ComplianceDocStatus,
    FuelType,
    InsuranceType,
    PermitType,
    VehicleComplianceType,
    VehicleOwnershipType,
    VehicleStatus,
    VehicleType,
)


def _normalize_reg(value: str) -> str:
    return value.replace(" ", "").replace("-", "").upper()


class VehicleBase(BaseModel):
    chassis_number: str | None = Field(None, max_length=50)
    engine_number: str | None = Field(None, max_length=50)
    make: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    manufacture_year: int | None = Field(None, ge=1900, le=2100)
    color: str | None = Field(None, max_length=50)
    load_capacity_kg: float | None = Field(None, ge=0)
    seating_capacity: int | None = Field(None, ge=0)
    vehicle_type: VehicleType | None = None
    ownership_type: VehicleOwnershipType | None = None
    fuel_type: FuelType | None = None
    battery_capacity_kwh: float | None = Field(None, gt=0)
    owner_user_id: int | None = Field(None, gt=0)
    fleet_partner_id: int | None = Field(None, gt=0)
    hub_id: int | None = Field(None, gt=0)
    registered_owner_name: str | None = Field(None, max_length=150)
    vltd_device_id: str | None = Field(None, max_length=100)
    gps_device_id: str | None = Field(None, max_length=100)
    fastag_id: str | None = Field(None, max_length=50)
    is_company_fleet: bool | None = None
    zoho_id: str | None = Field(None, max_length=50)
    notes: str | None = None
    custom_attributes: dict | None = None


class VehicleCreate(VehicleBase):
    registration_number: str = Field(..., min_length=4, max_length=20)
    vehicle_type: VehicleType
    ownership_type: VehicleOwnershipType

    @field_validator("registration_number")
    @classmethod
    def _norm(cls, v: str) -> str:
        return _normalize_reg(v)


class VehicleUpdate(VehicleBase):
    registration_number: str | None = Field(None, min_length=4, max_length=20)
    status: VehicleStatus | None = None
    row_version: int = Field(..., ge=1)

    @field_validator("registration_number")
    @classmethod
    def _norm(cls, v: str | None) -> str | None:
        return _normalize_reg(v) if v else v


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: object
    id: int
    tenant_id: int
    organization_id: int
    registration_number: str
    chassis_number: str | None = None
    engine_number: str | None = None
    make: str | None = None
    model: str | None = None
    manufacture_year: int | None = None
    color: str | None = None
    load_capacity_kg: float | None = None
    seating_capacity: int | None = None
    vehicle_type: str
    ownership_type: str
    fuel_type: str | None = None
    battery_capacity_kwh: float | None = None
    owner_user_id: int | None = None
    fleet_partner_id: int | None = None
    hub_id: int | None = None
    registered_owner_name: str | None = None
    vltd_device_id: str | None = None
    gps_device_id: str | None = None
    fastag_id: str | None = None
    is_company_fleet: bool
    status: str
    rc_status_cache: str | None = None
    overall_compliance_status_cache: str | None = None
    is_verified: bool
    verification_status: str
    zoho_id: str | None = None
    notes: str | None = None
    custom_attributes: dict = {}
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class VehicleSlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: object
    id: int
    registration_number: str
    vehicle_type: str
    ownership_type: str
    status: str


class VehicleComplianceCreate(BaseModel):
    compliance_type: VehicleComplianceType
    document_id: int | None = Field(None, gt=0)
    certificate_number: str | None = Field(None, max_length=100)
    insurer_name: str | None = Field(None, max_length=255)
    insurance_type: InsuranceType | None = None
    permit_type: PermitType | None = None
    permit_region: str | None = Field(None, max_length=100)
    issued_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_upto: dt.date | None = None
    status: ComplianceDocStatus = ComplianceDocStatus.PENDING_RENEWAL
    renewed_from_id: int | None = Field(None, gt=0)


class VehicleComplianceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: object
    id: int
    vehicle_id: int
    document_id: int | None = None
    compliance_type: str
    certificate_number: str | None = None
    insurer_name: str | None = None
    insurance_type: str | None = None
    permit_type: str | None = None
    permit_region: str | None = None
    issued_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_upto: dt.date | None = None
    status: str
    renewed_from_id: int | None = None
    created_at: dt.datetime


class DrivingLicenseCreate(BaseModel):
    user_id: int = Field(..., gt=0)
    document_id: int | None = Field(None, gt=0)
    dl_number_masked: str | None = Field(None, max_length=30)
    dl_number_encrypted: str | None = None
    dl_classes: list[str] = []
    issuing_rto: str | None = Field(None, max_length=100)
    issue_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_upto: dt.date
    is_commercial_license: bool = False
    badge_number: str | None = Field(None, max_length=50)
    badge_issuing_authority: str | None = Field(None, max_length=150)
    badge_valid_upto: dt.date | None = None
    verified_via_parivahan: bool = False
    parivahan_reference_id: str | None = Field(None, max_length=150)


class DrivingLicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: object
    id: int
    user_id: int
    document_id: int | None = None
    dl_number_masked: str | None = None
    dl_classes: list = []
    issuing_rto: str | None = None
    issue_date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_upto: dt.date
    is_commercial_license: bool
    badge_number: str | None = None
    badge_valid_upto: dt.date | None = None
    verification_status: str
    verified_via_parivahan: bool
    is_current: bool
    created_at: dt.datetime
