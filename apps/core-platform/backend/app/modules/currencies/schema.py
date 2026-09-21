"""Transport schemas for the canonical currency module.

Money crosses the wire as a decimal string / number, never as a float that has
already lost precision; rates are ``Decimal``. ``id`` is always the public
``uuid`` — the BigInteger primary key never leaves the database.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.currencies.enums import (
    CurrencyKind,
    RoundingMethod,
    RateUpdateFrequency,
    SymbolPlacement,
    VerificationStatus,
)


# ── exchange rates ──────────────────────────────────────────────────────────

class ExchangeRateIn(BaseModel):
    rate: Decimal = Field(..., ge=0, max_digits=15, decimal_places=6)
    effective_date: dt.date
    rate_source: str | None = Field(None, max_length=50, description="zoho / rbi / ecb / manual / ...")
    rate_type: str | None = Field(None, max_length=50, description="spot / reference / average / ...")
    is_active: bool = True
    sync_metadata: dict | None = None


class ExchangeRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(validation_alias="uuid")
    currency_id: int
    rate: Decimal
    effective_date: dt.date
    status: str
    is_active: bool | None = None
    rate_source: str | None = None
    rate_type: str | None = None
    verification_status: str
    created_at: dt.datetime


# ── requests ────────────────────────────────────────────────────────────────

class CurrencyCreate(BaseModel):
    currency_code: str | None = Field(None, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    currency_name: str | None = Field(None, max_length=255)
    currency_symbol: str | None = Field(None, max_length=16)
    iso_numeric_code: str | None = Field(None, max_length=3)
    country_code: str | None = Field(None, max_length=2)
    kind: CurrencyKind | None = CurrencyKind.FIAT

    price_precision: int | None = Field(None, ge=0, le=8)
    decimal_separator: str | None = Field(None, min_length=1, max_length=1)
    thousand_separator: str | None = Field(None, min_length=1, max_length=1)
    symbol_placement: SymbolPlacement | None = SymbolPlacement.BEFORE
    space_between_symbol: bool | None = None
    secondary_grouping_size: int | None = Field(None, ge=0, le=4)
    region_specific_formatting: dict | None = None
    use_regional_settings: bool | None = None

    is_default_currency: bool | None = None
    is_base_currency: bool | None = None
    is_active: bool | None = None
    allow_transactions: bool | None = None

    rounding_method: RoundingMethod | None = RoundingMethod.ROUND
    rounding_precision: int | None = Field(None, ge=0, le=8)
    apply_rounding_to_total_only: bool | None = None

    auto_update_rate: bool | None = None
    rate_update_frequency: RateUpdateFrequency | None = None

    gl_account_code: str | None = Field(None, max_length=64)
    require_exchange_rate_entry: bool | None = None
    allow_override_rate: bool | None = None

    rate_fluctuation_threshold: Decimal | None = Field(None, ge=0, max_digits=5, decimal_places=2)
    risk_management_rules: dict | None = None
    requires_authorization: bool | None = None

    metadata_: dict | None = None

    # The Zoho source echoes may be supplied by an importer; normal clients omit them.
    currency_id: str | None = Field(None, max_length=64)
    zoho_id: str | None = Field(None, max_length=64)


class CurrencyUpdate(BaseModel):
    """PATCH — only the fields you send change. ``row_version`` is the version
    you loaded; a mismatch is a 409 rather than a silent overwrite."""

    currency_name: str | None = Field(None, max_length=255)
    currency_symbol: str | None = Field(None, max_length=16)
    iso_numeric_code: str | None = Field(None, max_length=3)
    country_code: str | None = Field(None, max_length=2)
    kind: CurrencyKind | None = None

    price_precision: int | None = Field(None, ge=0, le=8)
    decimal_separator: str | None = Field(None, min_length=1, max_length=1)
    thousand_separator: str | None = Field(None, min_length=1, max_length=1)
    symbol_placement: SymbolPlacement | None = None
    space_between_symbol: bool | None = None
    secondary_grouping_size: int | None = Field(None, ge=0, le=4)
    region_specific_formatting: dict | None = None
    use_regional_settings: bool | None = None

    is_default_currency: bool | None = None
    is_base_currency: bool | None = None
    is_active: bool | None = None
    allow_transactions: bool | None = None

    rounding_method: RoundingMethod | None = None
    rounding_precision: int | None = Field(None, ge=0, le=8)
    apply_rounding_to_total_only: bool | None = None

    auto_update_rate: bool | None = None
    rate_update_frequency: RateUpdateFrequency | None = None

    gl_account_code: str | None = Field(None, max_length=64)
    require_exchange_rate_entry: bool | None = None
    allow_override_rate: bool | None = None

    rate_fluctuation_threshold: Decimal | None = Field(None, ge=0, max_digits=5, decimal_places=2)
    risk_management_rules: dict | None = None
    requires_authorization: bool | None = None

    metadata_: dict | None = None

    row_version: int = Field(..., ge=1)


class CurrencyVerify(BaseModel):
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    verification_method: str = Field(..., max_length=50, description="manual_review / rate_feed / api / ...")
    verification_data: dict | None = None


# ── responses ───────────────────────────────────────────────────────────────

class CurrencySlim(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(validation_alias="uuid")
    currency_code: str | None = None
    currency_name: str | None = None
    currency_symbol: str | None = None
    kind: str | None = None
    status: str
    is_base_currency: bool | None = None
    is_default_currency: bool | None = None
    is_active: bool | None = None
    exchange_rate: Decimal | None = None


class CurrencyOut(CurrencySlim):
    tenant_id: int
    organization_id: int
    currency_id: str | None = None
    zoho_id: str | None = None
    iso_numeric_code: str | None = None
    country_code: str | None = None

    price_precision: int | None = None
    decimal_separator: str | None = None
    thousand_separator: str | None = None
    symbol_placement: str | None = None
    space_between_symbol: bool | None = None
    secondary_grouping_size: int | None = None
    region_specific_formatting: dict | None = None
    use_regional_settings: bool | None = None

    allow_transactions: bool | None = None
    exchange_rate_as_of: dt.datetime | None = None
    exchange_rate_source: str | None = None
    auto_update_rate: bool | None = None
    rate_update_frequency: str | None = None

    rounding_method: str | None = None
    rounding_precision: int | None = None
    apply_rounding_to_total_only: bool | None = None

    gl_account_code: str | None = None
    require_exchange_rate_entry: bool | None = None
    allow_override_rate: bool | None = None
    rate_fluctuation_threshold: Decimal | None = None
    requires_authorization: bool | None = None

    is_verified: bool
    verification_status: str
    verification_method: str | None = None
    verification_data: dict | None = None
    verified_at: dt.datetime | None = None

    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    metadata_: dict | None = None

    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime