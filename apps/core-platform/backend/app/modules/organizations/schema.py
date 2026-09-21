"""Transport schemas for organizations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.tenants.enums import OrganizationStatus, OrganizationType

_CODE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,49}$"


def _month(value: Any) -> int | None:
    """Accept both Zoho shapes for a month: 0–11 or a name ('april', 'Apr')."""
    if value is None or value == "":
        return None
    from app.modules.zoho.sync.mapper import TRANSFORMS

    month = TRANSFORMS["month_index"](value)
    if month is None:
        raise ValueError("fiscal_year_start_month must be 0–11 or a month name (e.g. 'april')")
    return month


class OrganizationProfile(BaseModel):
    """Editable profile fields (all optional). For a Zoho-linked node the
    Zoho-owned ones are refused on update — edit them in Zoho."""

    trading_name: str | None = Field(None, max_length=255)
    tax_id: str | None = Field(None, max_length=50)
    currency_id: int | None = None
    timezone: str | None = Field(None, max_length=50)
    custom_attributes: dict | None = None
    name: str | None = Field(None, max_length=255)
    contact_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=255)
    industry_type: str | None = Field(None, max_length=100)
    industry_size: str | None = Field(None, max_length=100)
    language_code: str | None = Field(None, max_length=10)
    date_format: str | None = Field(None, max_length=50)
    fiscal_year_start_month: int | None = None
    address_street1: str | None = Field(None, max_length=255)
    address_street2: str | None = Field(None, max_length=255)
    address_city: str | None = Field(None, max_length=100)
    address_state: str | None = Field(None, max_length=100)
    address_country: str | None = Field(None, max_length=100)
    address_zip: str | None = Field(None, max_length=20)

    @field_validator("fiscal_year_start_month", mode="before")
    @classmethod
    def _fiscal_month(cls, value: Any) -> int | None:
        return _month(value)


class OrganizationCreate(OrganizationProfile):
    org_code: str = Field(..., pattern=_CODE)
    legal_name: str = Field(..., min_length=1, max_length=255)
    org_type: OrganizationType = OrganizationType.LEGAL_ENTITY
    parent: uuid.UUID | None = Field(None, description="uuid of the parent node; empty = a root")


class OrganizationUpdate(OrganizationProfile):
    """PATCH: only provided fields change. ``row_version`` = the version you loaded."""

    legal_name: str | None = Field(None, min_length=1, max_length=255)
    org_code: str | None = Field(None, pattern=_CODE)
    row_version: int = Field(..., ge=1)


class OrganizationMove(BaseModel):
    parent: uuid.UUID | None = Field(None, description="new parent uuid; empty = make it a root")
    row_version: int = Field(..., ge=1)


class OrganizationStatusChange(BaseModel):
    status: OrganizationStatus
    reason: str | None = Field(None, max_length=500)


class OrganizationSlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    org_code: str
    legal_name: str
    trading_name: str | None = None
    org_type: str
    status: str
    depth: int
    parent_uuid: uuid.UUID | None = None
    zoho_id: str | None = None


class OrganizationOut(OrganizationSlim):
    id: int
    tenant_id: int
    hierarchy_path: str
    is_verified: bool
    tax_id: str | None = None
    currency_id: int | None = None
    timezone: str | None = None
    custom_attributes: dict = {}
    name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    industry_type: str | None = None
    industry_size: str | None = None
    is_default_org: bool | None = None
    language_code: str | None = None
    time_zone: str | None = None
    date_format: str | None = None
    field_separator: str | None = None
    fiscal_year_start_month: int | None = None
    tax_group_enabled: bool | None = None
    account_created_date: date | None = None
    is_org_active: bool | None = None
    currency_code: str | None = None
    currency_symbol: str | None = None
    address_street1: str | None = None
    address_street2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    address_zip: str | None = None
    deactivation_date: datetime | None = None
    deactivation_reason: str | None = None
    synced_at: datetime | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationNode(OrganizationSlim):
    """Tree view: a node with its children."""

    children: list[OrganizationNode] = []
