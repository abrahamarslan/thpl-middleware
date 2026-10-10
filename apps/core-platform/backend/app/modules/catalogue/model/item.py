"""Items — the SKU every estimate, invoice, credit note, sales return and stock movement names — and the
item-owned children:

    Item                 one Zoho item (crosswalk module ``items``, phase 3); rates per BASE unit; never stock
    ItemMerchandising    1:1 storefront/SEO content, a different owner than Zoho (never races items.row_version)
    ItemAttributeValue   a variant's value on one axis (composite FK: the option belongs to the attribute)
    ItemUnit             the packaging hierarchy (``item_unit.py``)
    ItemIdentifier       barcodes / codes, optionally per pack level (GS1: a GTIN per level)
    ItemComponent        BOM / kit / box contents (acyclic — trigger ``guard_item_component_cycle``)
    ItemSalesChannel     channel listings
    ItemVendor           suppliers (party.parties, role vendor — asserted by the service)

Capabilities by mixin (registered in the phase-2 migration): taxes (``tax.tax_assignments``), accounts
(sales / purchase / inventory_asset), categories, documents, media (gallery), comments, custom fields, tags.
Their write paths are their own modules' services/routes — every relationship here is viewonly.

Integrity the database owns: composite same-organization FKs everywhere; ``(item_id, item_unit_id)`` /
``(item_id, batch_id)`` composite FKs so a child can never name another item's level; CHECKs for the rules
we own (a kit is never stocked, expiry needs lots, lots need inventory tracking, …).

Loaders (stated): every relationship is ``lazy="raise"`` (to-one: ``joinedload``; collections:
``selectinload`` in ``crud.items.get_item``). Lists use ``load_only`` (Slim).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, DeactivationMixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.accounting.mixins import HasAccountsMixin
from app.modules.catalogue.enums import (
    CATALOGUE_SCHEMA,
    ComponentRole,
    Composition,
    DrugSchedule,
    IdentifierKind,
    IdentifierSource,
    ItemStatus,
    StorageCondition,
    TrackMode,
    ValuationMethod,
    values,
)
from app.modules.catalogue.model.item_unit import ItemUnit
from app.modules.catalogue.model.product import Product
from app.modules.catalogue.model.reference import ItemGroup, Unit
from app.modules.categories.mixins import HasCategoriesMixin
from app.modules.comments.mixins import HasCommentsMixin
from app.modules.custom_fields.mixins import HasCustomFieldsMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.media.mixins import HasMediaMixin
from app.modules.tags.mixins import HasTagsMixin
from app.modules.taxes.mixins import HasTaxesMixin

_S = CATALOGUE_SCHEMA
_LIVE = text("deleted_at IS NULL")
_MONEY = Numeric(18, 6)
_QTY = Numeric(18, 6)


def _scope_fk(table: str, column: str, target: str, *, ondelete: str = "RESTRICT",
              name: str | None = None) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "organization_id", column],
        [f"{target}.tenant_id", f"{target}.organization_id", f"{target}.id"],
        name=name or f"fk_{table}_{column.removesuffix('_id')}", ondelete=ondelete,
    )


def _level_fk(table: str, item_col: str, level_col: str, name: str) -> ForeignKeyConstraint:
    """(item, level) composite FK: the level must belong to THIS item."""
    return ForeignKeyConstraint(
        [item_col, level_col], [f"{_S}.item_units.item_id", f"{_S}.item_units.id"],
        name=f"fk_{table}_{name}", ondelete="RESTRICT",
    )


class Item(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, DeactivationMixin,
    HasTagsMixin, HasDocumentsMixin, HasMediaMixin, HasCommentsMixin, HasCustomFieldsMixin,
    HasCategoriesMixin, HasTaxesMixin, HasAccountsMixin, SoftDeleteFilteredMixin, Base,
):
    """The item (SKU) of one organization."""

    custom_fields_owner_type = "item"

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_items_scope_id"),
        _scope_fk("items", "product_id", f"{_S}.products"),
        _scope_fk("items", "item_group_id", f"{_S}.item_groups"),
        _scope_fk("items", "brand_id", "core.brands"),
        _scope_fk("items", "manufacturer_id", "core.manufacturers"),
        _scope_fk("items", "base_unit_id", f"{_S}.units"),
        _scope_fk("items", "weight_unit_id", f"{_S}.units"),
        _scope_fk("items", "dimension_unit_id", f"{_S}.units"),
        # items ↔ item_units is circular: created after both tables (ALTER in the migration).
        ForeignKeyConstraint(["id", "zoho_item_unit_id"], [f"{_S}.item_units.item_id", f"{_S}.item_units.id"],
                             name="fk_items_zoho_item_unit", ondelete="RESTRICT", use_alter=True),
        CheckConstraint("btrim(name) <> ''", name="ck_items_name_not_blank"),
        CheckConstraint("sku IS NULL OR btrim(sku) <> ''", name="ck_items_sku_not_blank"),
        CheckConstraint(f"status IN ({values(ItemStatus)})", name="ck_items_status"),
        CheckConstraint(f"composition IN ({values(Composition)})", name="ck_items_composition"),
        CheckConstraint(f"track_mode IN ({values(TrackMode)})", name="ck_items_track_mode"),
        CheckConstraint("track_mode = 'none' OR is_inventory_tracked", name="ck_items_track_requires_inventory"),
        CheckConstraint("NOT expiry_tracked OR track_mode IN ('batch','batch_serial')",
                        name="ck_items_expiry_requires_batch"),
        CheckConstraint("composition <> 'kit' OR NOT is_inventory_tracked", name="ck_items_kit_not_stocked"),
        CheckConstraint("can_be_sold OR can_be_purchased OR status IN ('inactive','discontinued')",
                        name="ck_items_can_trade"),
        CheckConstraint("shelf_life_days IS NULL OR shelf_life_days > 0", name="ck_items_shelf_life"),
        CheckConstraint(f"valuation_method IS NULL OR valuation_method IN ({values(ValuationMethod)})",
                        name="ck_items_valuation"),
        CheckConstraint(
            "(sales_rate IS NULL OR sales_rate >= 0) AND (purchase_rate IS NULL OR purchase_rate >= 0) "
            "AND (mrp IS NULL OR mrp >= 0)", name="ck_items_rates"),
        CheckConstraint(
            "(reorder_level_base IS NULL OR reorder_level_base >= 0) "
            "AND (minimum_order_qty_base IS NULL OR minimum_order_qty_base > 0) "
            "AND (maximum_order_qty_base IS NULL OR maximum_order_qty_base > 0) "
            "AND (maximum_order_qty_base IS NULL OR minimum_order_qty_base IS NULL "
            "OR maximum_order_qty_base >= minimum_order_qty_base)", name="ck_items_order_qty"),
        CheckConstraint(
            "(net_weight IS NULL OR net_weight >= 0) AND (gross_weight IS NULL OR gross_weight >= 0) "
            "AND (length IS NULL OR length >= 0) AND (width IS NULL OR width >= 0) AND (height IS NULL OR height >= 0)",
            name="ck_items_physical"),
        CheckConstraint(f"storage_condition IS NULL OR storage_condition IN ({values(StorageCondition)})",
                        name="ck_items_storage_condition"),
        CheckConstraint("storage_temp_max_c IS NULL OR storage_temp_min_c IS NULL "
                        "OR storage_temp_max_c >= storage_temp_min_c", name="ck_items_storage_temp"),
        CheckConstraint("country_of_origin IS NULL OR country_of_origin ~ '^[A-Z]{2}$'", name="ck_items_country"),
        CheckConstraint(f"drug_schedule IS NULL OR drug_schedule IN ({values(DrugSchedule)})",
                        name="ck_items_drug_schedule"),
        CheckConstraint("position >= 0", name="ck_items_position"),
        Index("uq_items_scope_sku", "tenant_id", "organization_id", "sku_normalized", unique=True,
              postgresql_where=text("deleted_at IS NULL AND sku IS NOT NULL")),
        Index("uq_items_scope_code", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL AND code IS NOT NULL")),
        Index("uq_items_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_items_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        Index("ix_items_generic_name_trgm", text("lower(generic_name) gin_trgm_ops"), postgresql_using="gin",
              postgresql_where=text("deleted_at IS NULL AND generic_name IS NOT NULL")),
        Index("ix_items_alias_names", "alias_names", postgresql_using="gin",
              postgresql_where=text("deleted_at IS NULL AND alias_names IS NOT NULL")),
        Index("ix_items_org_status", "organization_id", "status", postgresql_where=_LIVE),
        Index("ix_items_brand", "brand_id", postgresql_where=text("deleted_at IS NULL AND brand_id IS NOT NULL")),
        Index("ix_items_manufacturer", "manufacturer_id",
              postgresql_where=text("deleted_at IS NULL AND manufacturer_id IS NOT NULL")),
        Index("ix_items_product", "product_id", postgresql_where=text("deleted_at IS NULL AND product_id IS NOT NULL")),
        Index("ix_items_item_group", "item_group_id",
              postgresql_where=text("deleted_at IS NULL AND item_group_id IS NOT NULL")),
        Index("ix_items_hsn", "organization_id", "hsn_or_sac",
              postgresql_where=text("deleted_at IS NULL AND hsn_or_sac IS NOT NULL")),
        {"schema": _S,
         "comment": "The item (SKU) of one organization: what documents and stock movements reference. Zoho crosswalk "
                    "module `items`. Rates per base unit; stock is never stored here."},
    )

    # identity ----------------------------------------------------------------
    zoho_id: Mapped[str | None] = mapped_column(String(50), comment="Echo of Zoho item_id; identity of record is sync.sync_records.")
    sku: Mapped[str | None] = mapped_column(String(100))
    sku_normalized: Mapped[str | None] = mapped_column(String(100), Computed("upper(btrim(sku))", persisted=True))
    code: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))", persisted=True))
    print_name: Mapped[str | None] = mapped_column(
        Text, comment="Name printed on documents when it differs from name (short invoice text).")
    generic_name: Mapped[str | None] = mapped_column(
        Text, comment='Generic / salt composition as printed (e.g. "Paracetamol 500 mg"); searchable, drives substitution lookups.')
    alias_names: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), comment='Search synonyms and trade aliases ("Crocin" for a paracetamol SKU, local-language names).')
    description: Mapped[str | None] = mapped_column(Text)
    purchase_description: Mapped[str | None] = mapped_column(Text)
    source_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # classification ----------------------------------------------------------
    product_id: Mapped[int | None] = mapped_column(BigInteger)
    item_group_id: Mapped[int | None] = mapped_column(BigInteger)
    brand_id: Mapped[int | None] = mapped_column(BigInteger)
    manufacturer_id: Mapped[int | None] = mapped_column(BigInteger)
    product_type: Mapped[str | None] = mapped_column(
        String(32), comment="Zoho product_type (goods / service / digital_service / capital_*): Zoho's open set, no CHECK.")
    composition: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default=text("'none'"),
        comment="none | assembly (Zoho composite, combo_type=assembly: own stock, built from components) | kit "
                "(combo_type=kit: no own stock, components move).")
    # capabilities ------------------------------------------------------------
    can_be_sold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    can_be_purchased: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_inventory_tracked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Zoho track_inventory. Zoho item_type is derived: inventory if tracked, else sales / purchases / "
                "sales_and_purchases from can_be_*.")
    is_returnable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_fulfillable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_taxable: Mapped[bool | None] = mapped_column(Boolean)
    # lot / expiry / quality ----------------------------------------------------
    track_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default=text("'none'"),
        comment="none | batch | serial | batch_serial. serial is reserved: no serial tables are built yet (plan 04 §8).")
    expiry_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    requires_qc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    valuation_method: Mapped[str | None] = mapped_column(String(24))
    # units ---------------------------------------------------------------------
    base_unit_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The stocking unit every quantity resolves to. NULL only for thin Zoho items without a unit; "
                            "such an item transacts with factor 1 until fixed.")
    zoho_item_unit_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="The pack level Zoho's single item unit represents (NULL = the base level). Zoho rates/"
                            "quantities are converted through it on pull and push.")
    hsn_or_sac: Mapped[str | None] = mapped_column(String(16))
    # default commercial values (per BASE unit) ---------------------------------
    sales_rate: Mapped[Decimal | None] = mapped_column(_MONEY)
    purchase_rate: Mapped[Decimal | None] = mapped_column(_MONEY)
    mrp: Mapped[Decimal | None] = mapped_column(
        _MONEY, comment="Maximum retail price per base unit (Zoho label_rate). Batches may carry their own printed MRP.")
    mrp_includes_tax: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    reorder_level_base: Mapped[Decimal | None] = mapped_column(_QTY)
    minimum_order_qty_base: Mapped[Decimal | None] = mapped_column(_QTY)
    maximum_order_qty_base: Mapped[Decimal | None] = mapped_column(_QTY)
    # physical facts of ONE base unit ---------------------------------------------
    net_weight: Mapped[Decimal | None] = mapped_column(_QTY)
    gross_weight: Mapped[Decimal | None] = mapped_column(_QTY)
    weight_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    length: Mapped[Decimal | None] = mapped_column(_QTY)
    width: Mapped[Decimal | None] = mapped_column(_QTY)
    height: Mapped[Decimal | None] = mapped_column(_QTY)
    dimension_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    # storage & regulatory ----------------------------------------------------
    storage_condition: Mapped[str | None] = mapped_column(String(16))
    storage_temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    storage_temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    country_of_origin: Mapped[str | None] = mapped_column(String(2))
    drug_schedule: Mapped[str | None] = mapped_column(
        String(8), comment="Drugs and Cosmetics Rules schedule (H, H1, X, G…); verify vocabulary with the compliance owner.")
    requires_prescription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    internal_notes: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    # to-one (joinedload) ---------------------------------------------------------
    brand = relationship("Brand", primaryjoin="foreign(Item.brand_id) == Brand.id", viewonly=True, lazy="raise")
    manufacturer = relationship("Manufacturer", primaryjoin="foreign(Item.manufacturer_id) == Manufacturer.id",
                                viewonly=True, lazy="raise")
    base_unit: Mapped[Unit | None] = relationship(Unit, primaryjoin="foreign(Item.base_unit_id) == Unit.id",
                                                  viewonly=True, lazy="raise")
    item_group: Mapped[ItemGroup | None] = relationship(
        ItemGroup, primaryjoin="foreign(Item.item_group_id) == ItemGroup.id", viewonly=True, lazy="raise")
    product: Mapped[Product | None] = relationship(Product, primaryjoin="foreign(Item.product_id) == Product.id",
                                                   viewonly=True, lazy="raise")
    merchandising: Mapped[ItemMerchandising | None] = relationship(
        "ItemMerchandising", primaryjoin="Item.id == foreign(ItemMerchandising.item_id)", viewonly=True,
        uselist=False, lazy="raise")
    # collections (selectinload) ----------------------------------------------------
    units: Mapped[list[ItemUnit]] = relationship(
        ItemUnit, primaryjoin="Item.id == foreign(ItemUnit.item_id)",
        order_by="ItemUnit.base_factor.desc(), ItemUnit.id", viewonly=True, lazy="raise")
    identifiers: Mapped[list[ItemIdentifier]] = relationship(
        "ItemIdentifier", primaryjoin="Item.id == foreign(ItemIdentifier.item_id)",
        order_by="ItemIdentifier.kind, ItemIdentifier.id", viewonly=True, lazy="raise")
    components: Mapped[list[ItemComponent]] = relationship(
        "ItemComponent", primaryjoin="Item.id == foreign(ItemComponent.parent_item_id)",
        order_by="ItemComponent.position, ItemComponent.id", viewonly=True, lazy="raise")
    channels: Mapped[list[ItemSalesChannel]] = relationship(
        "ItemSalesChannel", primaryjoin="Item.id == foreign(ItemSalesChannel.item_id)",
        order_by="ItemSalesChannel.id", viewonly=True, lazy="raise")
    vendors: Mapped[list[ItemVendor]] = relationship(
        "ItemVendor", primaryjoin="Item.id == foreign(ItemVendor.item_id)",
        order_by="ItemVendor.is_preferred.desc(), ItemVendor.position, ItemVendor.id", viewonly=True, lazy="raise")
    attribute_values: Mapped[list[ItemAttributeValue]] = relationship(
        "ItemAttributeValue", primaryjoin="Item.id == foreign(ItemAttributeValue.item_id)",
        order_by="ItemAttributeValue.attribute_id", viewonly=True, lazy="raise")

    @property
    def item_type(self) -> str:
        """Zoho's item_type, derived (never stored)."""
        if self.is_inventory_tracked:
            return "inventory"
        if self.can_be_sold and self.can_be_purchased:
            return "sales_and_purchases"
        return "sales" if self.can_be_sold else "purchases"

    def __repr__(self) -> str:
        return f"<Item id={self.id} sku={self.sku!r} name={self.name!r}>"


class ItemMerchandising(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """1:1 storefront/SEO content of an item; locally owned, never written by the Zoho sync."""

    __tablename__ = "item_merchandising"
    __table_args__ = (
        _scope_fk("item_merchandising", "item_id", f"{_S}.items", ondelete="CASCADE"),
        CheckConstraint("slug IS NULL OR slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_item_merchandising_slug"),
        CheckConstraint("menu_position >= 0", name="ck_item_merchandising_menu_position"),
        Index("uq_item_merchandising_item", "item_id", unique=True, postgresql_where=_LIVE),
        Index("uq_item_merchandising_slug", "tenant_id", "organization_id", "slug", unique=True,
              postgresql_where=text("deleted_at IS NULL AND slug IS NOT NULL")),
        {"schema": _S, "comment": "1:1 storefront/SEO content of an item; locally owned, never written by the Zoho sync."},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    tagline: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str | None] = mapped_column(Text)
    short_description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    seo_title: Mapped[str | None] = mapped_column(Text)
    seo_description: Mapped[str | None] = mapped_column(Text)
    seo_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    specifications: Mapped[dict | None] = mapped_column(JSONB)
    specification_set_ref: Mapped[str | None] = mapped_column(String(64))
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    show_in_menu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    menu_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class ItemAttributeValue(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """The value of one variant axis on an item (Volume = 95 ml)."""

    __tablename__ = "item_attribute_values"
    __table_args__ = (
        _scope_fk("item_attribute_values", "item_id", f"{_S}.items", ondelete="CASCADE"),
        _scope_fk("item_attribute_values", "attribute_id", f"{_S}.attributes"),
        ForeignKeyConstraint(["attribute_id", "attribute_option_id"],
                             [f"{_S}.attribute_options.attribute_id", f"{_S}.attribute_options.id"],
                             name="fk_item_attribute_values_option", ondelete="RESTRICT"),
        Index("uq_item_attribute_values_axis", "item_id", "attribute_id", unique=True, postgresql_where=_LIVE),
        {"schema": _S},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attribute_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attribute_option_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ItemIdentifier(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A barcode or code of an item, optionally per pack level (``item_unit_id`` NULL = base)."""

    __tablename__ = "item_identifiers"
    __table_args__ = (
        _scope_fk("item_identifiers", "item_id", f"{_S}.items", ondelete="CASCADE"),
        _level_fk("item_identifiers", "item_id", "item_unit_id", "item_unit"),
        CheckConstraint(f"kind IN ({values(IdentifierKind)})", name="ck_item_identifiers_kind"),
        CheckConstraint("btrim(value) <> ''", name="ck_item_identifiers_value_not_blank"),
        CheckConstraint(
            "CASE kind WHEN 'gtin' THEN value_normalized ~ '^[0-9]{8}$|^[0-9]{12,14}$' "
            "WHEN 'ean' THEN value_normalized ~ '^[0-9]{8}$|^[0-9]{13}$' "
            "WHEN 'upc' THEN value_normalized ~ '^[0-9]{12}$' "
            "WHEN 'isbn' THEN value_normalized ~ '^[0-9]{9}[0-9X]$|^[0-9]{13}$' ELSE true END",
            name="ck_item_identifiers_format"),
        CheckConstraint(f"source IN ({values(IdentifierSource)})", name="ck_item_identifiers_source"),
        Index("uq_item_identifiers_scannable", "tenant_id", "organization_id", "value_normalized", unique=True,
              postgresql_where=text("deleted_at IS NULL AND kind IN ('gtin','ean','upc','isbn','barcode')")),
        Index("uq_item_identifiers_primary", "item_id", "item_unit_id", "kind", unique=True,
              postgresql_where=text("deleted_at IS NULL AND is_primary"), postgresql_nulls_not_distinct=True),
        Index("ix_item_identifiers_lookup", "tenant_id", "organization_id", "kind", "value_normalized",
              postgresql_where=_LIVE),
        Index("ix_item_identifiers_item", "item_id", postgresql_where=_LIVE),
        {"schema": _S,
         "comment": "Barcodes/codes of an item, optionally per pack level (item_unit_id NULL = the base unit). Zoho "
                    "upc/ean/isbn/part_number land here."},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"upper(regexp_replace(value, '\s+', '', 'g'))", persisted=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local", server_default=text("'local'"))


class ItemComponent(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A component of an assembly / kit / box (Zoho composite items' mapped_items)."""

    __tablename__ = "item_components"
    __table_args__ = (
        _scope_fk("item_components", "parent_item_id", f"{_S}.items", ondelete="CASCADE", name="fk_item_components_parent"),
        _scope_fk("item_components", "component_item_id", f"{_S}.items", name="fk_item_components_component"),
        _level_fk("item_components", "component_item_id", "component_item_unit_id", "component_unit"),
        CheckConstraint("parent_item_id <> component_item_id", name="ck_item_components_not_self"),
        CheckConstraint(f"role IN ({values(ComponentRole)})", name="ck_item_components_role"),
        CheckConstraint("quantity > 0", name="ck_item_components_quantity"),
        CheckConstraint("wastage_pct >= 0 AND wastage_pct < 100", name="ck_item_components_wastage"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_item_components_window"),
        Index("uq_item_components_current", "parent_item_id", "component_item_id", "role", unique=True,
              postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL")),
        Index("ix_item_components_component", "component_item_id", postgresql_where=_LIVE),
        {"schema": _S,
         "comment": "Components of an assembly/kit/box (Zoho composite items mapped_items). Acyclic (trigger "
                    "guard_item_component_cycle)."},
    )

    parent_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    component_item_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_QTY, nullable=False)
    wastage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0, server_default=text("0"))
    substitute_group: Mapped[str | None] = mapped_column(String(40))
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False, default=dt.date.today, server_default=text("CURRENT_DATE"))
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
    zoho_id: Mapped[str | None] = mapped_column(String(50))


class ItemSalesChannel(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A channel listing of an item."""

    __tablename__ = "item_sales_channels"
    __table_args__ = (
        _scope_fk("item_sales_channels", "item_id", f"{_S}.items", ondelete="CASCADE"),
        _scope_fk("item_sales_channels", "sales_channel_id", f"{_S}.sales_channels", name="fk_item_sales_channels_channel"),
        _level_fk("item_sales_channels", "item_id", "price_item_unit_id", "price_unit"),
        CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_item_sales_channels_price"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_item_sales_channels_window"),
        Index("uq_item_sales_channels_current", "item_id", "sales_channel_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL")),
        Index("ix_item_sales_channels_channel", "sales_channel_id", postgresql_where=_LIVE),
        {"schema": _S,
         "comment": "Channel listings of an item; price_override (per price_item_unit_id, NULL = base) sits below a "
                    "party price list in the quote order."},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sales_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_listed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    channel_sku: Mapped[str | None] = mapped_column(String(100))
    channel_title: Mapped[str | None] = mapped_column(Text)
    price_override: Mapped[Decimal | None] = mapped_column(_MONEY)
    price_item_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False, default=dt.date.today, server_default=text("CURRENT_DATE"))
    valid_to: Mapped[dt.date | None] = mapped_column(Date)


class ItemVendor(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A supplier of an item (party role vendor, asserted by the service)."""

    __tablename__ = "item_vendors"
    __table_args__ = (
        _scope_fk("item_vendors", "item_id", f"{_S}.items", ondelete="CASCADE"),
        _scope_fk("item_vendors", "vendor_id", "party.parties"),
        _level_fk("item_vendors", "item_id", "purchase_item_unit_id", "purchase_unit"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_item_vendors_lead_time"),
        CheckConstraint("(min_order_qty IS NULL OR min_order_qty > 0) AND (last_purchase_rate IS NULL OR last_purchase_rate >= 0)",
                        name="ck_item_vendors_qty_rate"),
        Index("uq_item_vendors_pair", "item_id", "vendor_id", unique=True, postgresql_where=_LIVE),
        Index("uq_item_vendors_preferred", "item_id", unique=True, postgresql_where=text("deleted_at IS NULL AND is_preferred")),
        Index("ix_item_vendors_vendor", "vendor_id", postgresql_where=_LIVE),
        {"schema": _S, "comment": "Suppliers of an item (party role vendor, asserted by the service). Zoho vendor_id = the preferred one."},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vendor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vendor_sku: Mapped[str | None] = mapped_column(String(100))
    vendor_item_name: Mapped[str | None] = mapped_column(Text)
    purchase_item_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    min_order_qty: Mapped[Decimal | None] = mapped_column(_QTY)
    last_purchase_rate: Mapped[Decimal | None] = mapped_column(_MONEY)
    last_purchased_on: Mapped[dt.date | None] = mapped_column(Date)
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))



__all__ = ["Item", "ItemAttributeValue", "ItemComponent", "ItemIdentifier", "ItemMerchandising",
           "ItemSalesChannel", "ItemVendor"]
