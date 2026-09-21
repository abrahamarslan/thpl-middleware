"""Transport schemas for the location hub.

Coordinates cross the wire as plain ``latitude`` / ``longitude`` numbers —
clients should never have to build WKT, and the API should never accept
geometry text it would have to sanitise. The service turns the pair into the
single ``coordinates`` point, and Postgres generates the decimals back.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.geo.enums import (
    AdminLevel,
    FenceType,
    LinkType,
    PlaceKind,
    PlaceRelationshipType,
    PlaceStatus,
    TransportMode,
    VerificationStatus,
)
from app.modules.geo.model.link import OWNER_TYPES

class Coordinates(BaseModel):
    """A point, the only shape the API accepts for a position."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


# ── places ──────────────────────────────────────────────────────────────────

class PostalFields(BaseModel):
    """The postal block. Every field optional — half an address is still worth
    storing, and a courier with a landmark beats a geocoder with nothing."""

    attention: str | None = Field(None, max_length=255)
    formatted_address: str | None = None
    building_name: str | None = Field(None, max_length=255)
    street: str | None = Field(None, max_length=255)
    street2: str | None = Field(None, max_length=255)
    landmark: str | None = Field(None, max_length=255)
    sub_locality: str | None = Field(None, max_length=255)
    locality: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    district: str | None = Field(None, max_length=100)
    taluka: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    state_code: str | None = Field(None, max_length=10)
    postal_code: str | None = Field(None, max_length=16)
    country: str | None = Field(None, max_length=100)
    country_code: str | None = Field(None, min_length=2, max_length=2)
    phone: str | None = Field(None, max_length=50)
    fax: str | None = Field(None, max_length=50)
    contact_person_name: str | None = Field(None, max_length=255)
    contact_email: str | None = Field(None, max_length=255)


class PlaceCreate(PostalFields):
    kind: PlaceKind = PlaceKind.ADDRESS
    location_name: str | None = Field(None, max_length=255)
    is_primary: bool = False
    parent_location: uuid_lib.UUID | None = Field(None, description="uuid of the containing place")
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    timezone: str | None = Field(None, max_length=64)
    operating_hours: dict | None = None
    custom_attributes: dict | None = None
    app_metadata: dict | None = None

    @model_validator(mode="after")
    def _coordinates_come_in_pairs(self) -> PlaceCreate:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class PlaceUpdate(PlaceCreate):
    """PATCH — only the fields you send change. ``row_version`` is the version
    you loaded; a mismatch is a 409 rather than a silent overwrite."""

    kind: PlaceKind | None = None
    is_primary: bool | None = None
    status: PlaceStatus | None = None
    row_version: int = Field(..., ge=1)


class PlaceVerify(BaseModel):
    verification_status: VerificationStatus = VerificationStatus.FIELD_VERIFIED
    verification_method: str = Field(..., max_length=50, description="field_visit, utility_bill, otp, geocode …")
    verification_data: dict | None = None


class PlaceSlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    kind: str
    location_name: str | None = None
    formatted_address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str
    is_verified: bool
    is_primary: bool
    zoho_id: str | None = None

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: Any) -> float | None:
        return None if value is None else float(value)


class PlaceOut(PlaceSlim):
    id: int
    tenant_id: int
    organization_id: int
    geohash8: str | None = None
    attention: str | None = None
    building_name: str | None = None
    street: str | None = None
    street2: str | None = None
    landmark: str | None = None
    sub_locality: str | None = None
    locality: str | None = None
    district: str | None = None
    taluka: str | None = None
    state_code: str | None = None
    country_code: str | None = None
    phone: str | None = None
    fax: str | None = None
    contact_person_name: str | None = None
    contact_email: str | None = None
    parent_location_id: int | None = None
    verification_status: str
    verification_method: str | None = None
    verified_at: dt.datetime | None = None
    provider: str | None = None
    provider_place_id: str | None = None
    plus_code: str | None = None
    geocode_confidence: float | None = None
    geocoded_at: dt.datetime | None = None
    timezone: str | None = None
    admin_boundary_id: int | None = None
    operating_hours: dict | None = None
    custom_attributes: dict = {}
    app_metadata: dict = {}
    app_version: str | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


# ── addresses (place links) ─────────────────────────────────────────────────

class AddressBase(BaseModel):
    link_type: LinkType = LinkType.PRIMARY
    purpose: str = Field("", max_length=50)
    label: str | None = Field(None, max_length=100)
    is_primary: bool = False
    attention: str | None = Field(None, max_length=255)
    landmark: str | None = Field(None, max_length=255)
    delivery_instructions: str | None = Field(None, max_length=500)
    contact_phone: str | None = Field(None, max_length=50)
    valid_from: dt.datetime | None = None
    valid_to: dt.datetime | None = None
    custom_attributes: dict | None = None
    app_metadata: dict | None = None


class AddressCreate(AddressBase):
    """Attach an address to an owner.

    Give either ``place`` (an existing place's uuid) or ``new_place`` (create
    one and link it in the same call) — the common case is a user typing an
    address into a form that has never been seen before.
    """

    owner_type: str = Field(..., max_length=50)
    owner_id: int = Field(..., gt=0)
    place: uuid_lib.UUID | None = None
    new_place: PlaceCreate | None = None
    freeze: bool = Field(
        False, description="Copy the address into an immutable snapshot (documents)",
    )

    @field_validator("owner_type")
    @classmethod
    def _known_owner(cls, value: str) -> str:
        if value not in OWNER_TYPES:
            raise ValueError(f"owner_type must be one of: {', '.join(OWNER_TYPES)}")
        return value

    @model_validator(mode="after")
    def _one_place(self) -> AddressCreate:
        if (self.place is None) == (self.new_place is None):
            raise ValueError("give exactly one of 'place' or 'new_place'")
        return self


class AddressUpdate(AddressBase):
    link_type: LinkType | None = None
    purpose: str | None = Field(None, max_length=50)
    is_primary: bool | None = None
    status: str | None = Field(None, pattern="^(active|suspended|archived)$")
    row_version: int = Field(..., ge=1)


class AddressVerify(PlaceVerify):
    """Verifying the link says "this owner really is here" — a different claim
    from "these coordinates are right", which is verifying the place."""


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    id: int
    tenant_id: int
    organization_id: int
    owner_type: str
    owner_id: int
    link_type: str
    purpose: str
    label: str | None = None
    is_primary: bool
    status: str
    attention: str | None = None
    landmark: str | None = None
    delivery_instructions: str | None = None
    contact_phone: str | None = None
    valid_from: dt.datetime
    valid_to: dt.datetime | None = None
    is_verified: bool
    verification_status: str
    verification_method: str | None = None
    verified_at: dt.datetime | None = None
    snapshot: dict | None = None
    custom_attributes: dict = {}
    app_metadata: dict = {}
    app_version: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    place: PlaceSlim | None = None


# ── geofences ───────────────────────────────────────────────────────────────

class GeofenceBase(BaseModel):
    name: str | None = Field(None, max_length=255)
    fence_type: FenceType | None = None
    place: uuid_lib.UUID | None = Field(None, description="Place this fence guards")
    center: Coordinates | None = None
    radius_m: float | None = Field(None, gt=0)
    polygon: list[Coordinates] | None = Field(
        None, min_length=3, description="Ring of points; closed automatically",
    )
    dwell_threshold_s: int | None = Field(None, ge=0)
    speed_limit_kmh: float | None = Field(None, gt=0)
    entry_alert: bool | None = None
    exit_alert: bool | None = None
    tags: list[str] | None = None
    valid_from: dt.datetime | None = None
    valid_to: dt.datetime | None = None
    custom_attributes: dict | None = None


class GeofenceCreate(GeofenceBase):
    name: str = Field(..., max_length=255)
    fence_type: FenceType = FenceType.CUSTOM

    @model_validator(mode="after")
    def _has_a_shape(self) -> GeofenceCreate:
        if self.polygon is None and not (self.center and self.radius_m):
            raise ValueError("give a polygon, or a center with a radius_m")
        return self


class GeofenceUpdate(GeofenceBase):
    status: str | None = Field(None, pattern="^(active|suspended|archived)$")
    row_version: int = Field(..., ge=1)


class GeofenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    id: int
    name: str
    fence_type: str
    status: str
    place_id: int | None = None
    radius_m: float | None = None
    dwell_threshold_s: int
    speed_limit_kmh: float | None = None
    entry_alert: bool
    exit_alert: bool
    tags: list[str] | None = None
    valid_from: dt.datetime | None = None
    valid_to: dt.datetime | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    custom_attributes: dict = {}
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime


# ── reference ───────────────────────────────────────────────────────────────

class AdminBoundaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    id: int
    level: str
    name: str
    name_local: str | None = None
    path: str
    depth: int
    parent_id: int | None = None
    lgd_code: str | None = None
    census_code: str | None = None
    state_code: str | None = None
    iso_code: str | None = None
    pincode: str | None = None
    timezone: str | None = None
    status: str


class AdminBoundaryCreate(BaseModel):
    level: AdminLevel
    name: str = Field(..., max_length=255)
    name_local: str | None = Field(None, max_length=255)
    alt_names: list[str] | None = None
    parent_id: int | None = None
    lgd_code: str | None = Field(None, max_length=32)
    census_code: str | None = Field(None, max_length=32)
    state_code: str | None = Field(None, max_length=10)
    iso_code: str | None = Field(None, max_length=16)
    pincode: str | None = Field(None, max_length=16)
    timezone: str | None = Field(None, max_length=64)
    centroid: Coordinates | None = None
    custom_attributes: dict | None = None


# ── relationships ───────────────────────────────────────────────────────────

class PlaceRelationshipCreate(BaseModel):
    related_place: uuid_lib.UUID
    relationship_type: PlaceRelationshipType = PlaceRelationshipType.ROUTE_SEGMENT
    transport_mode: TransportMode = TransportMode.DRIVING
    is_bidirectional: bool = False
    sequence_number: int | None = None
    duration_s: float | None = Field(None, ge=0)
    routing_metadata: dict | None = None


class PlaceRelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_lib.UUID
    id: int
    place_id: int
    related_place_id: int
    relationship_type: str
    transport_mode: str
    is_bidirectional: bool
    sequence_number: int | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    bearing_deg: float | None = None
    status: str
    created_at: dt.datetime
