"""Transport schemas of the catalogue masters.

Slim vs Fat: lists return ``*SlimOut`` (backed by ``load_only`` in crud); details return ``*Out``.
Updates are PATCH with the ``row_version`` you loaded (mismatch → 409). Quantities and factors travel
as decimals (JSON strings), never floats.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalogue.enums import AttributeInputType, ChannelKind, MasterStatus, UnitClass

_CODE_UPPER = r"^[A-Za-z0-9_]+$"     # stored upper-cased
_CODE_LOWER = r"^[A-Za-z0-9_]+$"     # stored lower-cased


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _Audit(_Out):
    organization_id: int
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class _Versioned(BaseModel):
    row_version: int = Field(..., ge=1, description="The version you loaded; a mismatch is a 409")


# ── UQC ──────────────────────────────────────────────────────────────────────

class UqcCodeOut(_Out):
    code: str
    description: str
    quantity_kind: str
    is_active: bool


# ── units ────────────────────────────────────────────────────────────────────

class UnitSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    unit_class: str
    uqc_code: str | None = None
    decimal_places: int
    si_factor: Decimal | None = None
    is_system: bool
    status: str


class UnitOut(UnitSlimOut, _Audit):
    plural_name: str | None = None
    zoho_id: str | None = None


class UnitCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=200)
    plural_name: str | None = Field(None, max_length=200)
    unit_class: UnitClass
    uqc_code: str | None = Field(None, min_length=3, max_length=3)
    decimal_places: int = Field(0, ge=0, le=6)
    si_factor: Decimal | None = Field(None, gt=0, description="Physical units only: multiplier to g / ml / mm / mm2 / s")


class UnitUpdate(_Versioned):
    code: str | None = Field(None, min_length=1, max_length=32)
    name: str | None = Field(None, min_length=1, max_length=200)
    plural_name: str | None = Field(None, max_length=200)
    uqc_code: str | None = Field(None, min_length=3, max_length=3)
    decimal_places: int | None = Field(None, ge=0, le=6)
    si_factor: Decimal | None = Field(None, gt=0)
    status: MasterStatus | None = None


# ── packaging types ──────────────────────────────────────────────────────────

class PackagingTypeSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    is_container: bool
    is_display_unit: bool
    is_stackable: bool
    icon: str | None = None
    status: str


class PackagingTypeOut(PackagingTypeSlimOut, _Audit):
    description: str | None = None
    is_dangler: bool
    stack_limit: int | None = None
    handling_instructions: str | None = None
    storage_requirements: str | None = None
    standard_weight: Decimal | None = None
    weight_unit_id: int | None = None
    standard_length: Decimal | None = None
    standard_width: Decimal | None = None
    standard_height: Decimal | None = None
    dimension_unit_id: int | None = None
    properties: dict | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class PackagingTypeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    is_container: bool = False
    is_dangler: bool = False
    is_display_unit: bool = False
    is_stackable: bool = False
    stack_limit: int | None = Field(None, gt=0)
    handling_instructions: str | None = None
    storage_requirements: str | None = None
    standard_weight: Decimal | None = Field(None, ge=0)
    weight_unit_id: int | None = Field(None, ge=1)
    standard_length: Decimal | None = Field(None, ge=0)
    standard_width: Decimal | None = Field(None, ge=0)
    standard_height: Decimal | None = Field(None, ge=0)
    dimension_unit_id: int | None = Field(None, ge=1)
    icon: str | None = Field(None, max_length=64)
    properties: dict | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class PackagingTypeUpdate(_Versioned):
    code: str | None = Field(None, min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    is_container: bool | None = None
    is_dangler: bool | None = None
    is_display_unit: bool | None = None
    is_stackable: bool | None = None
    stack_limit: int | None = Field(None, gt=0)
    handling_instructions: str | None = None
    storage_requirements: str | None = None
    standard_weight: Decimal | None = Field(None, ge=0)
    weight_unit_id: int | None = Field(None, ge=1)
    standard_length: Decimal | None = Field(None, ge=0)
    standard_width: Decimal | None = Field(None, ge=0)
    standard_height: Decimal | None = Field(None, ge=0)
    dimension_unit_id: int | None = Field(None, ge=1)
    icon: str | None = Field(None, max_length=64)
    properties: dict | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    status: MasterStatus | None = None


# ── sales channels ───────────────────────────────────────────────────────────

class SalesChannelSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    channel_kind: str | None = None
    zoho_code: str | None = None
    position: int
    status: str


class SalesChannelOut(SalesChannelSlimOut, _Audit):
    description: str | None = None


class SalesChannelCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    channel_kind: ChannelKind | None = None
    zoho_code: str | None = Field(None, min_length=1, max_length=32)
    position: int = Field(0, ge=0, le=32767)


class SalesChannelUpdate(_Versioned):
    code: str | None = Field(None, min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    channel_kind: ChannelKind | None = None
    zoho_code: str | None = Field(None, min_length=1, max_length=32)
    position: int | None = Field(None, ge=0, le=32767)
    status: MasterStatus | None = None


# ── item groups ──────────────────────────────────────────────────────────────

class ItemGroupSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    parent_id: int | None = None
    is_visible: bool
    show_in_menu: bool
    display_order: int
    status: str


class ItemGroupOut(ItemGroupSlimOut, _Audit):
    description: str | None = None


class ItemGroupNode(ItemGroupSlimOut):
    """One node of ``GET /item-groups?tree=true`` (children nested, ordered)."""

    children: list[ItemGroupNode] = []


class ItemGroupCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    parent_id: int | None = Field(None, ge=1)
    is_visible: bool = True
    show_in_menu: bool = True
    display_order: int = Field(0, ge=0)


class ItemGroupUpdate(_Versioned):
    code: str | None = Field(None, min_length=1, max_length=40, pattern=_CODE_UPPER)
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    parent_id: int | None = Field(None, ge=1)
    is_visible: bool | None = None
    show_in_menu: bool | None = None
    display_order: int | None = Field(None, ge=0)
    status: MasterStatus | None = None


# ── attributes ───────────────────────────────────────────────────────────────

class AttributeOptionOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    attribute_id: int
    value: str
    numeric_value: Decimal | None = None
    swatch: str | None = None
    position: int
    status: str
    row_version: int


class AttributeSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    code: str
    name: str
    input_type: str
    unit_id: int | None = None
    status: str


class AttributeOut(AttributeSlimOut, _Audit):
    options: list[AttributeOptionOut] = []


class AttributeOptionCreate(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    numeric_value: Decimal | None = None
    swatch: str | None = Field(None, max_length=32)
    position: int = Field(0, ge=0, le=32767)


class AttributeOptionUpdate(_Versioned):
    value: str | None = Field(None, min_length=1, max_length=200)
    numeric_value: Decimal | None = None
    swatch: str | None = Field(None, max_length=32)
    position: int | None = Field(None, ge=0, le=32767)
    status: MasterStatus | None = None


class AttributeCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=_CODE_LOWER)
    name: str = Field(..., min_length=1, max_length=200)
    input_type: AttributeInputType = AttributeInputType.SELECT
    unit_id: int | None = Field(None, ge=1)
    options: list[AttributeOptionCreate] = Field(default_factory=list, max_length=500)


class AttributeUpdate(_Versioned):
    code: str | None = Field(None, min_length=1, max_length=40, pattern=_CODE_LOWER)
    name: str | None = Field(None, min_length=1, max_length=200)
    input_type: AttributeInputType | None = None
    unit_id: int | None = Field(None, ge=1)
    status: MasterStatus | None = None


__all__ = [name for name in dir() if name.endswith(("Out", "Create", "Update", "Node"))]
