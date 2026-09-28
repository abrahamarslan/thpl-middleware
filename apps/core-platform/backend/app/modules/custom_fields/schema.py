"""Transport schemas for the custom-fields engine.

Writes are typed by what the field *means*, not by which physical column holds
it: a value is submitted as a plain JSON scalar and the service places it in the
column the definition's data type dictates. That keeps the five-column storage
detail out of every client.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.modules.custom_fields.enums import PiiType


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── data types (global lookup) ───────────────────────────────────────────────

class DataTypeOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    label: str | None = None
    storage_column: str


# ── field definitions ────────────────────────────────────────────────────────

class FieldDefinitionCreate(BaseModel):
    owner_type_code: str = Field(..., min_length=1, max_length=64,
                                 description="A code registered in core.entity_types")
    data_type_code: str = Field(..., min_length=1, max_length=64,
                                description="A code from GET /api/custom-fields/data-types")
    api_name: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=255)
    placeholder: str | None = Field(None, max_length=255)
    help_text: str | None = None
    default_value: str | None = None
    sort_order: int | None = Field(None, ge=0)
    precision: int | None = Field(None, ge=0, le=38)
    max_length: int | None = Field(None, gt=0)
    is_mandatory: bool | None = None
    is_mandatory_in_sales_item: bool | None = None
    is_mandatory_in_storefront: bool | None = None
    is_mandatory_in_hp: bool | None = None
    show_in_store: bool | None = None
    show_in_hp: bool | None = None
    show_in_all_pdf: bool | None = None
    edit_on_store: bool | None = None
    is_read_only: bool | None = None
    is_active: bool | None = True
    is_dependent_field: bool | None = None
    depends_on_field_id: int | None = Field(None, ge=1)
    is_inherited_value: bool | None = None
    is_basecurrency_amount: bool | None = None
    pii_type: PiiType | None = None


class FieldDefinitionUpdate(BaseModel):
    row_version: int = Field(..., ge=1)
    data_type_code: str | None = Field(None, min_length=1, max_length=64)
    label: str | None = Field(None, min_length=1, max_length=255)
    placeholder: str | None = Field(None, max_length=255)
    help_text: str | None = None
    default_value: str | None = None
    sort_order: int | None = Field(None, ge=0)
    precision: int | None = Field(None, ge=0, le=38)
    max_length: int | None = Field(None, gt=0)
    is_mandatory: bool | None = None
    is_mandatory_in_sales_item: bool | None = None
    is_mandatory_in_storefront: bool | None = None
    is_mandatory_in_hp: bool | None = None
    show_in_store: bool | None = None
    show_in_hp: bool | None = None
    show_in_all_pdf: bool | None = None
    edit_on_store: bool | None = None
    is_read_only: bool | None = None
    is_active: bool | None = None
    is_dependent_field: bool | None = None
    depends_on_field_id: int | None = Field(None, ge=1)
    is_inherited_value: bool | None = None
    is_basecurrency_amount: bool | None = None
    pii_type: PiiType | None = None


class FieldDefinitionSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    owner_type_code: str
    data_type_id: int
    api_name: str
    label: str
    is_active: bool | None = None
    is_mandatory: bool | None = None
    sort_order: int | None = None
    pii_type: str | None = None


class FieldDefinitionOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    owner_type_code: str
    data_type_id: int
    api_name: str
    label: str
    placeholder: str | None = None
    help_text: str | None = None
    default_value: str | None = None
    sort_order: int | None = None
    precision: int | None = None
    max_length: int | None = None
    is_mandatory: bool | None = None
    is_mandatory_in_sales_item: bool | None = None
    is_mandatory_in_storefront: bool | None = None
    is_mandatory_in_hp: bool | None = None
    show_in_store: bool | None = None
    show_in_hp: bool | None = None
    show_in_all_pdf: bool | None = None
    edit_on_store: bool | None = None
    is_read_only: bool | None = None
    is_active: bool | None = None
    is_dependent_field: bool | None = None
    depends_on_field_id: int | None = None
    is_inherited_value: bool | None = None
    is_basecurrency_amount: bool | None = None
    pii_type: str | None = None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    data_type: DataTypeOut | None = None


# ── field values ─────────────────────────────────────────────────────────────

class FieldValueSet(BaseModel):
    """Set one value for one owner (idempotent upsert)."""

    field_definition_id: int = Field(..., ge=1)
    owner_type_code: str = Field(..., min_length=1, max_length=64)
    owner_id: int = Field(..., ge=1)
    value: Any = Field(None, description="A JSON scalar matching the field's data type; null clears it")


class FieldValueItem(BaseModel):
    field_definition_id: int = Field(..., ge=1)
    value: Any = None


class FieldValueSync(BaseModel):
    """Replace an owner's whole value set (the tags ``sync`` pattern)."""

    owner_type_code: str = Field(..., min_length=1, max_length=64)
    owner_id: int = Field(..., ge=1)
    values: list[FieldValueItem] = []


class FieldValueOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    field_definition_id: int
    owner_type_code: str
    owner_id: int
    value_text: str | None = None
    value_numeric: Decimal | None = None
    value_date: dt.datetime | None = None
    value_boolean: bool | None = None
    value_json: dict | list | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    field_definition: FieldDefinitionSlimOut | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value(self) -> Any:
        """The populated value, whichever typed column it lives in."""
        for candidate in (self.value_text, self.value_numeric, self.value_date,
                          self.value_boolean, self.value_json):
            if candidate is not None:
                return candidate
        return None


__all__ = [
    "DataTypeOut",
    "FieldDefinitionCreate",
    "FieldDefinitionOut",
    "FieldDefinitionSlimOut",
    "FieldDefinitionUpdate",
    "FieldValueItem",
    "FieldValueOut",
    "FieldValueSet",
    "FieldValueSync",
]