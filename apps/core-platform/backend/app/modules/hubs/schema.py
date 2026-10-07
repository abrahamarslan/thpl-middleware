"""Transport schemas for the hub module."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field

from app.modules.hubs.enums import HubStatus, HubType


class HubBase(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    hub_type: HubType | None = None
    parent_hub_id: int | None = Field(None, gt=0)
    place_id: int | None = Field(None, gt=0, description="geo.places.id — the hub address")
    geofence_id: int | None = Field(None, gt=0, description="geo.geofences.id — the hub zone")
    manager_user_id: int | None = Field(None, gt=0)
    contact_phone: str | None = Field(None, max_length=50)
    contact_email: str | None = Field(None, max_length=255)
    timezone: str | None = Field(None, max_length=64)
    operating_hours: dict | None = None
    daily_cutoff_time: dt.time | None = None
    storage_capacity_sqft: float | None = Field(None, ge=0)
    dock_count: int | None = Field(None, ge=0)
    vehicle_capacity: int | None = Field(None, ge=0)
    serviceable_pincodes: list[str] | None = None
    zoho_location_id: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=1000)
    custom_attributes: dict | None = None


class HubCreate(HubBase):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    hub_type: HubType = HubType.WAREHOUSE


class HubUpdate(HubBase):
    status: HubStatus | None = None
    row_version: int = Field(..., ge=1)


class HubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    organization_id: int
    code: str
    name: str
    hub_type: str
    status: str
    parent_hub_id: int | None = None
    place_id: int | None = None
    geofence_id: int | None = None
    manager_user_id: int | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    timezone: str | None = None
    operating_hours: dict | None = None
    daily_cutoff_time: dt.time | None = None
    storage_capacity_sqft: float | None = None
    dock_count: int | None = None
    vehicle_capacity: int | None = None
    serviceable_pincodes: list[str] | None = None
    zoho_location_id: str | None = None
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


class HubSlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    hub_type: str
    status: str


# ── user hub assignments (the hub of a day) ─────────────────────────────────────

class HubAssignmentIn(BaseModel):
    """One assignment: a single ``date``, or a ``valid_from`` … ``valid_to`` range (``valid_to`` omitted =
    open-ended). ``hub_id`` null = explicitly no hub on those days."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(..., gt=0)
    hub_id: int | None = Field(None, gt=0)
    date: dt.date | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    note: str | None = Field(None, max_length=500)

    def window(self) -> tuple[dt.date, dt.date | None]:
        if self.date is not None:
            return self.date, self.date
        if self.valid_from is None:
            raise ValueError("give a date, or valid_from (and optionally valid_to)")
        return self.valid_from, self.valid_to


class HubAssignmentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignments: list[HubAssignmentIn] = Field(..., min_length=1, max_length=500)


class HubAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    user_id: int
    hub_id: int | None
    valid_from: dt.date
    valid_to: dt.date | None
    source: str
    note: str | None
    created_at: dt.datetime


class HubOfDayOut(BaseModel):
    date: dt.date
    hub_id: int | None
    source: str | None = Field(None, description="assignment | employment | null (no hub)")
    hub: HubSlim | None = None
