"""Transport schemas of items, their packaging hierarchy and item-owned children, and products.

Slim (lists, ``load_only``) vs Fat (detail, explicit eager loads). Money / quantities / factors are
decimals (JSON strings). Updates are PATCH with the ``row_version`` you loaded (409 on mismatch).
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.catalogue.enums import (
    ComponentRole,
    Composition,
    DrugSchedule,
    IdentifierKind,
    ItemStatus,
    MasterStatus,
    StorageCondition,
    TrackMode,
    ValuationMethod,
)

_MONEY = Field(None, ge=0, max_digits=18, decimal_places=6)
_QTY_POS = Field(None, gt=0, max_digits=18, decimal_places=6)
_QTY_NONNEG = Field(None, ge=0, max_digits=18, decimal_places=6)


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _Versioned(BaseModel):
    row_version: int = Field(..., ge=1, description="The version you loaded; a mismatch is a 409")


class RefOut(_Out):
    """A compact reference to another row (brand, unit, group…)."""

    id: int
    uuid: uuid_lib.UUID | None = None
    name: str | None = None
    code: str | None = None


# ── packaging hierarchy ──────────────────────────────────────────────────────

class _LevelFields(BaseModel):
    label: str | None = Field(None, max_length=200)
    packaging_type_id: int | None = Field(None, ge=1)
    is_sellable: bool = True
    is_purchasable: bool = True
    is_default_sales: bool = False
    is_default_purchase: bool = False
    allow_break: bool = True
    min_order_qty: Decimal | None = _QTY_POS
    order_multiple: Decimal | None = _QTY_POS
    sales_rate: Decimal | None = _MONEY
    purchase_rate: Decimal | None = _MONEY
    mrp: Decimal | None = _MONEY
    derive_price: bool = False
    gross_weight: Decimal | None = _QTY_NONNEG
    weight_unit_id: int | None = Field(None, ge=1)
    length: Decimal | None = _QTY_NONNEG
    width: Decimal | None = _QTY_NONNEG
    height: Decimal | None = _QTY_NONNEG
    dimension_unit_id: int | None = Field(None, ge=1)
    special_instructions: str | None = None
    position: int = Field(0, ge=0, le=32767)


class ItemUnitCreate(_LevelFields):
    """A new pack level: ``unit_id`` contains ``contents_qty`` of the level ``contents_item_unit_id``
    (any CURRENT level of the same item, the base level included)."""

    unit_id: int = Field(..., ge=1)
    contents_item_unit_id: int = Field(..., ge=1)
    contents_qty: Decimal = Field(..., gt=0, max_digits=18, decimal_places=6)


class ItemUnitInline(_LevelFields):
    """A pack level inside an item create payload: ``contains`` names an earlier level by its UNIT id
    (the base unit or a unit listed before it)."""

    unit_id: int = Field(..., ge=1)
    contains_unit_id: int = Field(..., ge=1)
    contents_qty: Decimal = Field(..., gt=0, max_digits=18, decimal_places=6)


class ItemUnitUpdate(_Versioned):
    """Flags, prices, physicals and labels only — the structure is immutable (retire and replace)."""

    label: str | None = Field(None, max_length=200)
    packaging_type_id: int | None = Field(None, ge=1)
    is_sellable: bool | None = None
    is_purchasable: bool | None = None
    is_default_sales: bool | None = None
    is_default_purchase: bool | None = None
    allow_break: bool | None = None
    min_order_qty: Decimal | None = _QTY_POS
    order_multiple: Decimal | None = _QTY_POS
    sales_rate: Decimal | None = _MONEY
    purchase_rate: Decimal | None = _MONEY
    mrp: Decimal | None = _MONEY
    derive_price: bool | None = None
    gross_weight: Decimal | None = _QTY_NONNEG
    weight_unit_id: int | None = Field(None, ge=1)
    length: Decimal | None = _QTY_NONNEG
    width: Decimal | None = _QTY_NONNEG
    height: Decimal | None = _QTY_NONNEG
    dimension_unit_id: int | None = Field(None, ge=1)
    special_instructions: str | None = None
    position: int | None = Field(None, ge=0, le=32767)
    status: MasterStatus | None = None


class ItemUnitRetire(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
    replacement: ItemUnitCreate | None = Field(None, description="Optional new level created in the same call")


class ItemUnitOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    unit_id: int
    unit: RefOut | None = None
    is_base: bool
    contents_item_unit_id: int | None = None
    contents_qty: Decimal | None = None
    base_factor: Decimal
    label: str | None = None
    packaging_type_id: int | None = None
    is_sellable: bool
    is_purchasable: bool
    is_default_sales: bool
    is_default_purchase: bool
    allow_break: bool
    min_order_qty: Decimal | None = None
    order_multiple: Decimal | None = None
    sales_rate: Decimal | None = None
    purchase_rate: Decimal | None = None
    mrp: Decimal | None = None
    derive_price: bool
    gross_weight: Decimal | None = None
    weight_unit_id: int | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dimension_unit_id: int | None = None
    special_instructions: str | None = None
    valid_from: dt.date
    valid_to: dt.date | None = None
    position: int
    status: str
    row_version: int


class ConvertIn(BaseModel):
    """Either ``qty`` + ``from_item_unit_id`` + ``to_item_unit_id`` (conversion) or ``qty_base`` (breakdown)."""

    qty: Decimal | None = Field(None, gt=0)
    from_item_unit_id: int | None = Field(None, ge=1)
    to_item_unit_id: int | None = Field(None, ge=1)
    qty_base: Decimal | None = Field(None, gt=0)

    @model_validator(mode="after")
    def _one_shape(self) -> ConvertIn:
        conversion = None not in (self.qty, self.from_item_unit_id, self.to_item_unit_id)
        if conversion == (self.qty_base is not None):
            raise ValueError("send qty + from_item_unit_id + to_item_unit_id, or qty_base — not both, not neither")
        return self


class BreakdownPart(BaseModel):
    item_unit_id: int
    unit_code: str
    count: Decimal


class ConvertOut(BaseModel):
    quantity: Decimal | None = None
    breakdown: list[BreakdownPart] | None = None


# ── identifiers ──────────────────────────────────────────────────────────────

class IdentifierIn(BaseModel):
    kind: IdentifierKind
    value: str = Field(..., min_length=1, max_length=64)
    item_unit_id: int | None = Field(None, ge=1, description="The pack level the code is printed on; NULL = base")
    is_primary: bool = False


class IdentifierInline(BaseModel):
    """Inside an item create payload: the level is named by its UNIT id (NULL = base)."""

    kind: IdentifierKind
    value: str = Field(..., min_length=1, max_length=64)
    unit_id: int | None = Field(None, ge=1)
    is_primary: bool = False


class IdentifierOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    item_unit_id: int | None = None
    kind: str
    value: str
    is_primary: bool
    source: str


class LookupOut(BaseModel):
    item_id: int
    item_uuid: uuid_lib.UUID
    sku: str | None = None
    name: str
    item_unit_id: int | None = None
    unit_code: str | None = None
    base_factor: Decimal | None = None
    identifier_kind: str


# ── components, channels, vendors, axis values ───────────────────────────────

class ComponentIn(BaseModel):
    component_item_id: int = Field(..., ge=1)
    component_item_unit_id: int | None = Field(None, ge=1)
    role: ComponentRole
    quantity: Decimal = Field(..., gt=0, max_digits=18, decimal_places=6)
    wastage_pct: Decimal = Field(Decimal(0), ge=0, lt=100)
    substitute_group: str | None = Field(None, max_length=40)
    is_optional: bool = False
    position: int = Field(0, ge=0, le=32767)


class ComponentOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    component_item_id: int
    component_item_unit_id: int | None = None
    role: str
    quantity: Decimal
    wastage_pct: Decimal
    substitute_group: str | None = None
    is_optional: bool
    position: int
    valid_from: dt.date
    valid_to: dt.date | None = None


class ChannelIn(BaseModel):
    sales_channel_id: int = Field(..., ge=1)
    is_listed: bool = True
    channel_sku: str | None = Field(None, max_length=100)
    channel_title: str | None = None
    price_override: Decimal | None = _MONEY
    price_item_unit_id: int | None = Field(None, ge=1)


class ChannelOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    sales_channel_id: int
    is_listed: bool
    channel_sku: str | None = None
    channel_title: str | None = None
    price_override: Decimal | None = None
    price_item_unit_id: int | None = None
    valid_from: dt.date
    valid_to: dt.date | None = None


class VendorIn(BaseModel):
    vendor_id: int = Field(..., ge=1, description="party.parties id of a VENDOR")
    vendor_sku: str | None = Field(None, max_length=100)
    vendor_item_name: str | None = None
    purchase_item_unit_id: int | None = Field(None, ge=1)
    lead_time_days: int | None = Field(None, ge=0)
    min_order_qty: Decimal | None = _QTY_POS
    last_purchase_rate: Decimal | None = _MONEY
    last_purchased_on: dt.date | None = None
    is_preferred: bool = False
    position: int = Field(0, ge=0, le=32767)


class VendorOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    vendor_id: int
    vendor_sku: str | None = None
    vendor_item_name: str | None = None
    purchase_item_unit_id: int | None = None
    lead_time_days: int | None = None
    min_order_qty: Decimal | None = None
    last_purchase_rate: Decimal | None = None
    last_purchased_on: dt.date | None = None
    is_preferred: bool
    position: int


class AttributeValueIn(BaseModel):
    attribute_id: int = Field(..., ge=1)
    attribute_option_id: int = Field(..., ge=1)


class AttributeValueOut(_Out):
    id: int
    attribute_id: int
    attribute_option_id: int


# ── merchandising ────────────────────────────────────────────────────────────

class MerchandisingIn(BaseModel):
    display_name: str | None = Field(None, max_length=300)
    tagline: str | None = Field(None, max_length=300)
    slug: str | None = Field(None, max_length=200, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    short_description: str | None = None
    long_description: str | None = None
    is_featured: bool = False
    seo_title: str | None = Field(None, max_length=300)
    seo_description: str | None = None
    seo_keywords: list[str] | None = Field(None, max_length=50)
    specifications: dict | None = None
    specification_set_ref: str | None = Field(None, max_length=64)
    is_visible: bool = True
    show_in_menu: bool = True
    menu_position: int = Field(0, ge=0)


class MerchandisingOut(_Out):
    display_name: str | None = None
    tagline: str | None = None
    slug: str | None = None
    short_description: str | None = None
    long_description: str | None = None
    is_featured: bool
    seo_title: str | None = None
    seo_description: str | None = None
    seo_keywords: list[str] | None = None
    specifications: dict | None = None
    specification_set_ref: str | None = None
    is_visible: bool
    show_in_menu: bool
    menu_position: int
    row_version: int


# ── items ────────────────────────────────────────────────────────────────────

class _ItemScalars(BaseModel):
    """Every scalar a caller may set (create and update share it)."""

    sku: str | None = Field(None, min_length=1, max_length=100)
    code: str | None = Field(None, min_length=1, max_length=40)
    print_name: str | None = Field(None, max_length=300)
    generic_name: str | None = Field(None, max_length=500)
    alias_names: list[str] | None = Field(None, max_length=50)
    description: str | None = Field(None, max_length=2000)
    purchase_description: str | None = Field(None, max_length=2000)
    product_id: int | None = Field(None, ge=1)
    item_group_id: int | None = Field(None, ge=1)
    brand_id: int | None = Field(None, ge=1)
    manufacturer_id: int | None = Field(None, ge=1)
    product_type: str | None = Field(None, max_length=32)
    is_taxable: bool | None = None
    shelf_life_days: int | None = Field(None, gt=0)
    valuation_method: ValuationMethod | None = None
    hsn_or_sac: str | None = Field(None, pattern=r"^[0-9]{4,8}$")
    sales_rate: Decimal | None = _MONEY
    purchase_rate: Decimal | None = _MONEY
    mrp: Decimal | None = _MONEY
    reorder_level_base: Decimal | None = _QTY_NONNEG
    minimum_order_qty_base: Decimal | None = _QTY_POS
    maximum_order_qty_base: Decimal | None = _QTY_POS
    net_weight: Decimal | None = _QTY_NONNEG
    gross_weight: Decimal | None = _QTY_NONNEG
    weight_unit_id: int | None = Field(None, ge=1)
    length: Decimal | None = _QTY_NONNEG
    width: Decimal | None = _QTY_NONNEG
    height: Decimal | None = _QTY_NONNEG
    dimension_unit_id: int | None = Field(None, ge=1)
    storage_condition: StorageCondition | None = None
    storage_temp_min_c: Decimal | None = Field(None, ge=-100, le=100)
    storage_temp_max_c: Decimal | None = Field(None, ge=-100, le=100)
    country_of_origin: str | None = Field(None, pattern=r"^[A-Za-z]{2}$")
    drug_schedule: DrugSchedule | None = None
    internal_notes: str | None = None


class ItemCreate(_ItemScalars):
    """Create an item in ONE transaction, optionally with its whole description: storefront content,
    packaging hierarchy (base level from ``base_unit_id``, then ``units`` in order), barcodes, vendors,
    channel listings, variant values and components. Taxes, accounts, categories, custom fields, tags,
    documents and comments use their own modules' routes (owner type ``item``)."""

    name: str = Field(..., min_length=1, max_length=300)
    base_unit_id: int = Field(..., ge=1, description="The stocking unit; every quantity resolves to it")
    status: ItemStatus = ItemStatus.ACTIVE
    composition: Composition = Composition.NONE
    can_be_sold: bool = True
    can_be_purchased: bool = True
    is_inventory_tracked: bool = True
    is_returnable: bool = True
    is_fulfillable: bool = True
    track_mode: TrackMode = TrackMode.NONE
    expiry_tracked: bool = False
    requires_qc: bool = False
    mrp_includes_tax: bool = True
    requires_prescription: bool = False
    position: int = Field(0, ge=0)

    merchandising: MerchandisingIn | None = None
    base_level: _LevelFields | None = Field(None, description="Flags / prices of the base level")
    units: list[ItemUnitInline] = Field(default_factory=list, max_length=12)
    identifiers: list[IdentifierInline] = Field(default_factory=list, max_length=50)
    vendors: list[VendorIn] = Field(default_factory=list, max_length=50)
    channels: list[ChannelIn] = Field(default_factory=list, max_length=50)
    attribute_values: list[AttributeValueIn] = Field(default_factory=list, max_length=10)
    components: list[ComponentIn] = Field(default_factory=list, max_length=200)


class ItemUpdate(_ItemScalars, _Versioned):
    """Scalar fields only (children have their own routes; base unit: ``PUT /base-unit``)."""

    name: str | None = Field(None, min_length=1, max_length=300)
    composition: Composition | None = None
    can_be_sold: bool | None = None
    can_be_purchased: bool | None = None
    is_inventory_tracked: bool | None = None
    is_returnable: bool | None = None
    is_fulfillable: bool | None = None
    track_mode: TrackMode | None = None
    expiry_tracked: bool | None = None
    requires_qc: bool | None = None
    mrp_includes_tax: bool | None = None
    requires_prescription: bool | None = None
    position: int | None = Field(None, ge=0)


class ItemStatusChange(BaseModel):
    reason: str | None = Field(None, max_length=500)


class BaseUnitChange(_Versioned):
    base_unit_id: int = Field(..., ge=1)


class ItemSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    sku: str | None = None
    code: str | None = None
    name: str
    generic_name: str | None = None
    status: str
    brand_id: int | None = None
    item_group_id: int | None = None
    product_id: int | None = None
    base_unit_id: int | None = None
    hsn_or_sac: str | None = None
    sales_rate: Decimal | None = None
    mrp: Decimal | None = None
    track_mode: str
    can_be_sold: bool
    can_be_purchased: bool
    zoho_id: str | None = None


class ItemOut(ItemSlimOut):
    organization_id: int
    print_name: str | None = None
    alias_names: list[str] | None = None
    description: str | None = None
    purchase_description: str | None = None
    manufacturer_id: int | None = None
    product_type: str | None = None
    composition: str
    item_type: str
    is_inventory_tracked: bool
    is_returnable: bool
    is_fulfillable: bool
    is_taxable: bool | None = None
    expiry_tracked: bool
    shelf_life_days: int | None = None
    requires_qc: bool
    valuation_method: str | None = None
    zoho_item_unit_id: int | None = None
    purchase_rate: Decimal | None = None
    mrp_includes_tax: bool
    reorder_level_base: Decimal | None = None
    minimum_order_qty_base: Decimal | None = None
    maximum_order_qty_base: Decimal | None = None
    net_weight: Decimal | None = None
    gross_weight: Decimal | None = None
    weight_unit_id: int | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dimension_unit_id: int | None = None
    storage_condition: str | None = None
    storage_temp_min_c: Decimal | None = None
    storage_temp_max_c: Decimal | None = None
    country_of_origin: str | None = None
    drug_schedule: str | None = None
    requires_prescription: bool
    internal_notes: str | None = None
    position: int
    source_created_at: dt.datetime | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    brand: RefOut | None = None
    manufacturer: RefOut | None = None
    item_group: RefOut | None = None
    product: RefOut | None = None
    base_unit: RefOut | None = None
    merchandising: MerchandisingOut | None = None
    units: list[ItemUnitOut] = []
    identifiers: list[IdentifierOut] = []
    components: list[ComponentOut] = []
    channels: list[ChannelOut] = []
    vendors: list[VendorOut] = []
    attribute_values: list[AttributeValueOut] = []


class DataQualityOut(BaseModel):
    items_without_base_unit: int
    items_without_hsn: int
    goods_without_tax: int
    batch_items_without_expiry_rule: int
    levels_without_price: int


# ── products ─────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    slug: str | None = Field(None, max_length=200, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    code: str | None = Field(None, min_length=1, max_length=40)
    description: str | None = None
    brand_id: int | None = Field(None, ge=1)
    manufacturer_id: int | None = Field(None, ge=1)
    item_group_id: int | None = Field(None, ge=1)
    default_unit_id: int | None = Field(None, ge=1)
    attribute_ids: list[int] = Field(default_factory=list, max_length=10,
                                     description="The variant axes, in order (Zoho supports three)")


class ProductUpdate(_Versioned):
    name: str | None = Field(None, min_length=1, max_length=300)
    slug: str | None = Field(None, max_length=200, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    code: str | None = Field(None, min_length=1, max_length=40)
    description: str | None = None
    brand_id: int | None = Field(None, ge=1)
    manufacturer_id: int | None = Field(None, ge=1)
    item_group_id: int | None = Field(None, ge=1)
    default_unit_id: int | None = Field(None, ge=1)
    attribute_ids: list[int] | None = Field(None, max_length=10, description="Replace the axes (only while no variant exists)")
    status: MasterStatus | None = None


class ProductSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    name: str
    slug: str | None = None
    code: str | None = None
    brand_id: int | None = None
    item_group_id: int | None = None
    status: str


class ProductOut(ProductSlimOut):
    organization_id: int
    description: str | None = None
    manufacturer_id: int | None = None
    default_unit_id: int | None = None
    zoho_id: str | None = None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    attribute_ids: list[int] = []
    variants: list[ItemSlimOut] = []


__all__ = [name for name in list(globals()) if name.endswith(("Out", "In", "Create", "Update", "Inline", "Retire",
                                                              "Change", "Part"))]
