"""Transport schemas for tax assignments.

``TaxAssignmentItem`` is the ONE input shape for "these are my taxes", used by the
generic ``PUT /api/taxes/assignments/{owner_type}/{owner_id}`` AND embedded by any
module that lets its own create/update carry taxes (categories' ``tax_preferences``,
a future item's ``taxes``): one shape to learn, one place validation lives.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.taxes.enums import TaxSpecification, TaxTransactionType
from app.modules.taxes.schema import TaxComponentSlimOut, TaxExemptionOut


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TaxAssignmentItem(BaseModel):
    """One tax (or exemption) an entity carries, and the context it applies in."""

    tax: str | None = Field(
        None, description="A tax rate or group: its id, public uuid, or the source's id (e.g. Zoho's tax_id)",
    )
    tax_exemption: str | None = Field(None, description="An exemption instead of a tax: its id or public uuid")
    tax_specification: TaxSpecification | None = Field(None, description="inter / intra; empty = any")
    transaction_type: TaxTransactionType | None = Field(None, description="sales / purchase; empty = both")
    position: int = Field(0, ge=0, le=32000, description="Order when several taxes apply together")

    @model_validator(mode="after")
    def _exactly_one_target(self) -> TaxAssignmentItem:
        if (self.tax is None) == (self.tax_exemption is None):
            raise ValueError("Give exactly one of 'tax' or 'tax_exemption'")
        return self


class TaxAssignmentsReplace(BaseModel):
    items: list[TaxAssignmentItem] = Field(default_factory=list, max_length=50)


class TaxAssignmentOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    owner_type_code: str
    owner_id: int
    tax_specification: str | None = None
    transaction_type: str | None = None
    position: int = 0
    source_system: str | None = None
    is_pending: bool = False
    external_ref: str | None = None
    frozen_at: dt.datetime | None = None
    snapshot: dict | None = None
    tax: TaxComponentSlimOut | None = Field(None, validation_alias="tax_component")
    tax_exemption: TaxExemptionOut | None = None


class TaxableEntityTypeOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    entity_type_code: str
    allows_multiple: bool
    allows_exemption: bool
    is_enabled: bool
    description: str | None = None


class TaxResolutionOut(BaseModel):
    """Which tax applies here, and where the answer came from."""

    via: str = Field(description="owner | organization_default | none")
    resolved_from_type: str | None = None
    resolved_from_id: int | None = None
    taxes: list[TaxComponentSlimOut] = []
    exemptions: list[TaxExemptionOut] = []


__all__ = [
    "TaxAssignmentItem",
    "TaxAssignmentOut",
    "TaxAssignmentsReplace",
    "TaxResolutionOut",
    "TaxableEntityTypeOut",
]
