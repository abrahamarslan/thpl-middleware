"""Transport schemas for the organizations module."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrganizationBase(BaseModel):
    """Editable business fields (all optional — nullable-by-doctrine)."""

    name: str | None = Field(None, max_length=255)
    contact_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=255)
    industry_type: str | None = None
    industry_size: str | None = None
    language_code: str | None = Field(None, max_length=10)
    time_zone: str | None = None
    date_format: str | None = None
    field_separator: str | None = Field(None, max_length=10)
    fiscal_year_start_month: int | None = Field(None, ge=0, le=11)
    currency_code: str | None = Field(None, max_length=10)
    address_street1: str | None = None
    address_street2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    address_zip: str | None = Field(None, max_length=20)
    description: str | None = None


class OrganizationCreate(OrganizationBase):
    name: str = Field(..., min_length=1, max_length=255)


class OrganizationUpdate(OrganizationBase):
    """PATCH-style: only provided fields change (exclude_unset in service)."""


class OrganizationOut(OrganizationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None = None
    code: str | None = None
    # Read-only Zoho-managed attributes
    is_default_org: bool | None = None
    is_org_active: bool | None = None
    user_role: str | None = None
    user_status: str | None = None
    account_created_date: date | None = None
    tax_group_enabled: bool | None = None
    currency_id: str | None = None
    currency_symbol: str | None = None
    currency_format: str | None = None
    price_precision: int | None = None
    # Sync observability
    sync_status: str | None = None
    sync_error: str | None = None
    synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
