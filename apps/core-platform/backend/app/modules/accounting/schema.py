"""Request / response models of the accounting API.

Slim for lists (``AccountSlimOut`` — backed by ``load_only`` in crud), Fat for detail
(``AccountOut``). Presentation fields are computed, never stored.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── account types / purposes ─────────────────────────────────────────────────


class AccountTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    zoho_id: str | None
    name: str
    account_group: str
    default_normal_balance_is_debit: bool
    is_sub_account_allowed: bool | None
    can_show_opening_balance: bool | None
    can_enable_in_ze: bool | None
    asset_type: str | None
    is_documented: bool
    is_sales_eligible: bool
    is_purchase_eligible: bool
    is_inventory_eligible: bool
    is_enabled: bool
    sort_order: int


class AccountPurposeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    description: str | None
    allowed_groups: list[str]
    allowed_types: list[str] | None
    per_currency: bool
    is_enabled: bool


class AccountPurposePolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type_code: str
    purpose_code: str
    falls_back_to_organization: bool
    is_enabled: bool


# ── accounts ──────────────────────────────────────────────────────────────────


class AccountSlimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid_lib.UUID
    account_code: str | None
    account_name: str
    display_name: str
    account_type: str
    parent_id: int | None
    depth: int
    status: str
    normal_balance_is_debit: bool
    zoho_id: str | None


class AccountOut(AccountSlimOut):
    organization_id: int
    description: str | None
    currency_id: int | None
    is_contra: bool
    is_system_account: bool
    is_user_created: bool | None
    placeholder: str | None
    is_expense_claim_enabled: bool | None
    show_on_dashboard: bool | None
    is_register_supported: bool | None
    is_standalone: bool | None
    is_verified: bool
    verification_status: str
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    # Computed by the service (never stored):
    account_group: str | None = None
    parent_display_name: str | None = None
    has_children: bool = False
    assignment_count: int = 0


class AccountTreeNode(AccountSlimOut):
    children: list[AccountTreeNode] = Field(default_factory=list)


class _AccountWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("account_code", "account_name", "description", check_fields=False)
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class AccountCreate(_AccountWrite):
    account_name: str = Field(..., min_length=1, max_length=200)
    account_code: str | None = Field(None, max_length=50)
    account_type: str = Field(..., min_length=1, max_length=64)
    parent_id: int | None = Field(None, gt=0)
    description: str | None = Field(None, max_length=2000)
    currency_id: int | None = Field(None, gt=0)
    is_contra: bool = False
    is_expense_claim_enabled: bool | None = None
    show_on_dashboard: bool | None = None


class AccountUpdate(_AccountWrite):
    account_name: str | None = Field(None, min_length=1, max_length=200)
    account_code: str | None = Field(None, max_length=50)
    account_type: str | None = Field(None, min_length=1, max_length=64)
    parent_id: int | None = Field(None, gt=0)
    description: str | None = Field(None, max_length=2000)
    currency_id: int | None = Field(None, gt=0)
    is_contra: bool | None = None
    is_expense_claim_enabled: bool | None = None
    show_on_dashboard: bool | None = None


# ── assignments ───────────────────────────────────────────────────────────────


class AccountAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid_lib.UUID
    owner_type_code: str
    owner_id: int
    organization_id: int
    purpose_code: str
    account_id: int | None
    currency_id: int | None
    external_ref: str | None
    source_system: str | None
    is_pending: bool
    account: AccountSlimOut | None = None


class AccountAssignmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(..., min_length=1, max_length=48)
    account: str = Field(..., min_length=1, max_length=64, description="Account id or uuid")
    currency_id: int | None = Field(None, gt=0)


class AccountAssignmentsReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AccountAssignmentItem] = Field(default_factory=list, max_length=100)
    organization_id: int | None = Field(
        None, description="Only for a tenant-wide owner (a shared tax): which organization's chart to use",
    )


class ChartViolationOut(BaseModel):
    account_id: int
    display_name: str
    account_type: str
    parent_id: int
    parent_type: str
    reason: str


__all__ = [
    "AccountAssignmentItem",
    "AccountAssignmentOut",
    "AccountAssignmentsReplace",
    "AccountCreate",
    "AccountOut",
    "AccountPurposeOut",
    "AccountPurposePolicyOut",
    "AccountSlimOut",
    "AccountTreeNode",
    "AccountTypeOut",
    "AccountUpdate",
    "ChartViolationOut",
]
