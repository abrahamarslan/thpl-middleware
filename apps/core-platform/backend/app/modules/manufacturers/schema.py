"""Transport schemas for the ``core.manufacturers`` tables."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field

from app.modules.manufacturers.enums import ManufacturerIdentifierKind, ManufacturerStatus


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ManufacturerSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    name: str
    slug: str | None = None
    legal_name: str | None = None
    code: str | None = None
    status: str
    country_code: str | None = None
    is_verified: bool = False


class ManufacturerIdentifierOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    manufacturer_id: int
    kind: str | None = None
    value: str
    issuing_authority: str | None = None
    issued_on: dt.date | None = None
    expires_on: dt.date | None = None
    is_verified: bool = False
    verification_status: str
    verified_at: dt.datetime | None = None
    created_at: dt.datetime


class ManufacturerOut(ManufacturerSlimOut):
    organization_id: int
    owner_type: str | None = None
    owner_id: int | None = None
    website_url: str | None = None
    verification_status: str
    verification_method: str | None = None
    verified_at: dt.datetime | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    identifiers: list[ManufacturerIdentifierOut] = []


class ManufacturerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    slug: str | None = Field(None, max_length=200)
    legal_name: str | None = Field(None, max_length=500)
    code: str | None = Field(None, max_length=64)
    country_code: str | None = Field(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    website_url: str | None = Field(None, max_length=2048)


class ManufacturerUpdate(BaseModel):
    """PATCH — only the fields you send change. ``row_version`` is the version
    you loaded; a mismatch is a 409 rather than a silent overwrite."""

    name: str | None = Field(None, min_length=1, max_length=500)
    slug: str | None = Field(None, max_length=200)
    legal_name: str | None = Field(None, max_length=500)
    code: str | None = Field(None, max_length=64)
    country_code: str | None = Field(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    website_url: str | None = Field(None, max_length=2048)
    status: ManufacturerStatus | None = None

    row_version: int = Field(..., ge=1)


class ManufacturerIdentifierCreate(BaseModel):
    kind: ManufacturerIdentifierKind | None = None
    value: str = Field(..., min_length=1, max_length=200)
    issuing_authority: str | None = Field(None, max_length=255)
    issued_on: dt.date | None = None
    expires_on: dt.date | None = None


__all__ = [
    "ManufacturerCreate",
    "ManufacturerIdentifierCreate",
    "ManufacturerIdentifierOut",
    "ManufacturerOut",
    "ManufacturerSlimOut",
    "ManufacturerUpdate",
]
