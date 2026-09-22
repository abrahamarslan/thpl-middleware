"""Transport schemas for the tax module (read-only over the canonical tables).

Slim vs Fat (master prompt, ``<slim_fat_query_doctrine>``): lists return the
``*SlimOut`` shape, backed by ``load_only`` in crud so the database never sends
the columns a list will not render; a single component returns ``TaxComponentOut``
with its members and the external systems it is linked to.
"""

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaxComponentSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    tax_name: str
    tax_display_name: str | None = None
    tax_percentage: Decimal
    tax_type: str
    tax_specific_type: str | None = None
    tax_specification: str | None = None
    is_default_tax: bool | None = None
    is_inactive: bool | None = None
    status: str


class TaxGroupMemberOut(_Out):
    position: int | None = None
    member: TaxComponentSlimOut = Field(validation_alias="member_tax")


class TaxSourceOut(BaseModel):
    """One external system's view of a component (from the crosswalk)."""

    source_system: str
    module: str
    external_id: str
    link_state: str


class TaxComponentOut(TaxComponentSlimOut):
    """The full component: every business column, its members, its sources."""

    organization_id: int | None = None
    tax_factor: str | None = None
    is_value_added: bool | None = None
    tax_authority_id: str | None = None
    tax_authority_name: str | None = None
    country: str | None = None
    country_code: str | None = None
    output_tax_account_name: str | None = None
    purchase_tax_account_name: str | None = None
    tax_account_id: str | None = None
    purchase_tax_account_id: str | None = None
    tds_payable_account_id: str | None = None
    purchase_tax_expense_account_id: int | None = None
    is_state_cess: bool | None = None
    is_editable: bool | None = None
    is_non_advol_tax: bool | None = None
    diff_rate_reason: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    description: str | None = None
    reference_id: str | None = None
    tax_name_formatted: str | None = None
    source_default_tax_type_code: int | None = None
    source_new_tax_type: str | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    members: list[TaxGroupMemberOut] = []
    sources: list[TaxSourceOut] = []


class TaxExemptionOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    organization_id: int | None = None
    tax_exemption_code: str | None = None
    description: str | None = None
    type: str | None = None
    type_formatted: str | None = None
    exemption_name: str | None = None
    exemption_type: str | None = None
    exemption_type_formatted: str | None = None


class GstTreatmentTypeOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: int
    value: str
    label: str | None = None
    value_formatted: str | None = None
    description: str | None = None
    category: str | None = None
    allowed_for_sales: bool | None = None
    allowed_for_purchase: bool | None = None


class OrgDefaultTaxPreferenceOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    organization_id: int | None = None
    tax_specification: str
    default_tax: TaxComponentSlimOut
