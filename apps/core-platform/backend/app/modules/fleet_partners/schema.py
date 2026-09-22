"""Transport schemas for the fleet-partner module."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.modules.fleet_partners.enums import FleetPartnerEntityType, FleetPartnerStatus


class FleetPartnerBase(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    entity_type: FleetPartnerEntityType | None = None
    owner_user_id: int | None = Field(None, gt=0)
    pan_masked: str | None = Field(None, max_length=12)
    gstin: str | None = Field(None, max_length=20)
    cin: str | None = Field(None, max_length=25)
    tan: str | None = Field(None, max_length=20)
    registered_address_place_id: int | None = Field(None, gt=0)
    contact_person_name: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=50)
    contact_email: str | None = Field(None, max_length=255)
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    commission_rate: float | None = Field(None, ge=0, le=100)
    payment_terms_days: int | None = Field(None, ge=0)
    zoho_id: str | None = Field(None, max_length=50)
    notes: str | None = None
    custom_attributes: dict | None = None


class FleetPartnerCreate(FleetPartnerBase):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    entity_type: FleetPartnerEntityType = FleetPartnerEntityType.INDIVIDUAL


class FleetPartnerUpdate(FleetPartnerBase):
    status: FleetPartnerStatus | None = None
    row_version: int = Field(..., ge=1)


class FleetPartnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    organization_id: int
    code: str
    name: str
    entity_type: str
    status: str
    owner_user_id: int | None = None
    pan_masked: str | None = None
    gstin: str | None = None
    cin: str | None = None
    tan: str | None = None
    registered_address_place_id: int | None = None
    contact_person_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    commission_rate: float | None = None
    payment_terms_days: int | None = None
    zoho_id: str | None = None
    is_verified: bool
    verification_status: str
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    notes: str | None = None
    custom_attributes: dict = {}
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class FleetPartnerSlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    entity_type: str
    status: str
