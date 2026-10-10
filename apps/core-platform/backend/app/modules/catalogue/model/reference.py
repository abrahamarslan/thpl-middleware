"""``catalogue`` masters: the vocabularies every item is described with.

    UqcCode           GLOBAL GST Unit Quantity Codes (GSTN list) — national law, not tenant data
    Unit              every unit of one organization: count/trade units (PCS, BOX, CTN) AND physical
                      units (g, kg, ml, l, cm, in); ``unit_class`` + ``si_factor``
    PackagingType     physical packaging characteristics (monocarton, shipper case, dangler…)
    SalesChannel      route to market; ``zoho_code`` maps Zoho's contact ``sales_channel`` string
    ItemGroup         MERCHANDISING groups (Oral Care, Men's Grooming) — not categories, not Zoho
                      "item groups" (those are variant templates → ``Product``, phase 2)
    Attribute         a variant axis (Volume, Flavour) …
    AttributeOption   … and its values

Scoping: everything except ``UqcCode`` is ``OrgEntityMixin`` + soft delete (tenant AND organization NOT
NULL, composite FK to the organization). Children pin their parent's tenant and organization with
composite FKs to the parent's ``(tenant_id, organization_id, id)`` key.

Standard units: every organization gets the standard set (pcs, box, ctn, g, kg, ml, l, cm, in …) from
``catalogue.seed_standard_units()``, called by the migration for existing organizations and by the
``AFTER INSERT`` trigger ``trg_organizations_seed_catalogue`` for new ones. Zoho units (when the P0
probe finds an endpoint) adopt these rows by normalized code — decision D-6.

Loaders (stated): every relationship is ``lazy="raise"``; ``AttributeOption`` rows are read with an
explicit query (crud), never through a relationship, so nothing here can lazy-load.

Design: docs/implementation-plans/catalogue/ (02 §1, SQL §1–§2).
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
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.catalogue.enums import (
    CATALOGUE_SCHEMA,
    AttributeInputType,
    ChannelKind,
    MasterStatus,
    QuantityKind,
    UnitClass,
    values,
)

_LIVE = text("deleted_at IS NULL")
_S = CATALOGUE_SCHEMA


def _unit_fk(table: str, column: str) -> ForeignKeyConstraint:
    """Composite same-organization FK to ``catalogue.units``."""
    return ForeignKeyConstraint(
        ["tenant_id", "organization_id", column],
        [f"{_S}.units.tenant_id", f"{_S}.units.organization_id", f"{_S}.units.id"],
        name=f"fk_{table}_{column.removesuffix('_id')}", ondelete="RESTRICT",
    )


class UqcCode(Base):
    """A GST Unit Quantity Code. GLOBAL (reasoned entry in tests/test_tenancy.py)."""

    __tablename__ = "uqc_codes"
    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z]{3}$'", name="ck_uqc_codes_code"),
        CheckConstraint(f"quantity_kind IN ({values(QuantityKind)})", name="ck_uqc_codes_quantity_kind"),
        {"schema": _S,
         "comment": "GLOBAL: GST Unit Quantity Codes (GSTN list). Snapshotted on invoice lines for GSTR-1 / e-invoice."},
    )

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<UqcCode {self.code}>"


class Unit(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A unit of measure of one organization (count or physical)."""

    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_units_scope_id"),
        CheckConstraint("btrim(code) <> ''", name="ck_units_code_not_blank"),
        CheckConstraint("btrim(name) <> ''", name="ck_units_name_not_blank"),
        CheckConstraint(f"unit_class IN ({values(UnitClass)})", name="ck_units_class"),
        CheckConstraint("decimal_places BETWEEN 0 AND 6", name="ck_units_decimal_places"),
        # Count units have no universal size (that is what item_units is for).
        CheckConstraint(
            "(unit_class IN ('count','other') AND si_factor IS NULL) "
            "OR (unit_class NOT IN ('count','other') AND (si_factor IS NULL OR si_factor > 0))",
            name="ck_units_si_factor",
        ),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_units_status"),
        Index("uq_units_scope_code", "tenant_id", "organization_id", "code_normalized",
              unique=True, postgresql_where=_LIVE),
        Index("uq_units_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_units_class", "organization_id", "unit_class", postgresql_where=_LIVE),
        {"schema": _S,
         "comment": "Units of measure of one organization: count/trade and physical units (unit_class). "
                    "Zoho crosswalk module `units`."},
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="Symbol as printed (pcs, box, kg, ml)")
    code_normalized: Mapped[str | None] = mapped_column(
        String(32), Computed("lower(btrim(code))", persisted=True),
        comment="STORED lower-cased trimmed code; uniqueness per organization",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plural_name: Mapped[str | None] = mapped_column(Text)
    unit_class: Mapped[str] = mapped_column(String(16), nullable=False, comment="count / mass / volume / length / area / time / other")
    uqc_code: Mapped[str | None] = mapped_column(
        String(3), ForeignKey(f"{_S}.uqc_codes.code", ondelete="RESTRICT", name="fk_units_uqc"),
        comment="GST UQC this unit reports as; NULL = OTH at filing time",
    )
    decimal_places: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    si_factor: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 12), comment="Multiplier to the class base unit (g / ml / mm / mm2 / s); NULL for count units",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Seeded standard unit (catalogue.seed_standard_units)",
    )
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Echo of Zoho unit_id; identity of record is sync.sync_records",
    )

    def __repr__(self) -> str:
        return f"<Unit id={self.id} code={self.code!r} class={self.unit_class}>"


class PackagingType(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Packaging characteristics (EACH, MONOCARTON, SHIPPER_CASE…). How MANY lives on item_units."""

    __tablename__ = "packaging_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_packaging_types_scope_id"),
        _unit_fk("packaging_types", "weight_unit_id"),
        _unit_fk("packaging_types", "dimension_unit_id"),
        CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_packaging_types_code"),
        CheckConstraint("btrim(name) <> ''", name="ck_packaging_types_name_not_blank"),
        CheckConstraint("stack_limit IS NULL OR stack_limit > 0", name="ck_packaging_types_stack_limit"),
        CheckConstraint(
            "(standard_weight IS NULL OR standard_weight >= 0) AND (standard_length IS NULL OR standard_length >= 0) "
            "AND (standard_width IS NULL OR standard_width >= 0) AND (standard_height IS NULL OR standard_height >= 0)",
            name="ck_packaging_types_measures",
        ),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                        name="ck_packaging_types_window"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_packaging_types_status"),
        Index("uq_packaging_types_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=_LIVE),
        {"schema": _S,
         "comment": "Packaging characteristics (carton, monocarton, shipper case, dangler). Quantities live on catalogue.item_units."},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_container: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_dangler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_display_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_stackable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    stack_limit: Mapped[int | None] = mapped_column(Integer)
    handling_instructions: Mapped[str | None] = mapped_column(Text)
    storage_requirements: Mapped[str | None] = mapped_column(Text)
    standard_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    weight_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    standard_length: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    standard_width: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    standard_height: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    dimension_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    icon: Mapped[str | None] = mapped_column(String(64))
    properties: Mapped[dict | None] = mapped_column(
        JSONB, comment="Material facts (board_gsm, flute, recyclable); the pasted metadata_ — renamed (SQLAlchemy trap)",
    )
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)

    weight_unit: Mapped[Unit | None] = relationship(
        Unit, primaryjoin="foreign(PackagingType.weight_unit_id) == Unit.id", viewonly=True, lazy="raise",
    )
    dimension_unit: Mapped[Unit | None] = relationship(
        Unit, primaryjoin="foreign(PackagingType.dimension_unit_id) == Unit.id", viewonly=True, lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<PackagingType id={self.id} code={self.code!r}>"


class SalesChannel(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A route to market (general trade, distributor, e-commerce…)."""

    __tablename__ = "sales_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_sales_channels_scope_id"),
        CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_sales_channels_code"),
        CheckConstraint("btrim(name) <> ''", name="ck_sales_channels_name_not_blank"),
        CheckConstraint(f"channel_kind IS NULL OR channel_kind IN ({values(ChannelKind)})",
                        name="ck_sales_channels_kind"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_sales_channels_status"),
        Index("uq_sales_channels_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=_LIVE),
        Index("uq_sales_channels_zoho_code", "tenant_id", "organization_id", "zoho_code",
              unique=True, postgresql_where=text("deleted_at IS NULL AND zoho_code IS NOT NULL")),
        {"schema": _S,
         "comment": "Sales channels (route to market). Local master; zoho_code maps the Zoho contact sales_channel string."},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    channel_kind: Mapped[str | None] = mapped_column(String(24))
    zoho_code: Mapped[str | None] = mapped_column(
        String(32), comment="Zoho contact sales_channel value this channel stands for (e.g. direct_sales)",
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<SalesChannel id={self.id} code={self.code!r}>"


class ItemGroup(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A merchandising group, optionally nested (menus, catalogues, reporting lines, offer targets)."""

    __tablename__ = "item_groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_item_groups_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "parent_id"],
            [f"{_S}.item_groups.tenant_id", f"{_S}.item_groups.organization_id", f"{_S}.item_groups.id"],
            name="fk_item_groups_parent", ondelete="RESTRICT",
        ),
        CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_item_groups_code"),
        CheckConstraint("btrim(name) <> ''", name="ck_item_groups_name_not_blank"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_item_groups_no_self_parent"),
        CheckConstraint("display_order >= 0", name="ck_item_groups_display_order"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_item_groups_status"),
        Index("uq_item_groups_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=_LIVE),
        Index("ix_item_groups_parent", "parent_id", postgresql_where=text("parent_id IS NOT NULL AND deleted_at IS NULL")),
        {"schema": _S,
         "comment": "Merchandising groups (menus, catalogues, offer targets). Distinct from core.categories and "
                    "from Zoho item groups (= catalogue.products)."},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="Parent group; NULL = top level")
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    show_in_menu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<ItemGroup id={self.id} code={self.code!r}>"


class Attribute(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A variant axis (volume, pack size, flavour)."""

    __tablename__ = "attributes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_attributes_scope_id"),
        _unit_fk("attributes", "unit_id"),
        CheckConstraint("code ~ '^[a-z0-9_]+$'", name="ck_attributes_code"),
        CheckConstraint("btrim(name) <> ''", name="ck_attributes_name_not_blank"),
        CheckConstraint(f"input_type IN ({values(AttributeInputType)})", name="ck_attributes_input_type"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_attributes_status"),
        Index("uq_attributes_scope_code", "tenant_id", "organization_id", "code",
              unique=True, postgresql_where=_LIVE),
        {"schema": _S, "comment": "Variant axes (volume, pack size, flavour). Values in attribute_options."},
    )

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(String(16), nullable=False, default="select", server_default=text("'select'"))
    unit_id: Mapped[int | None] = mapped_column(BigInteger, comment="Unit of a numeric axis (ml for Volume)")

    def __repr__(self) -> str:
        return f"<Attribute id={self.id} code={self.code!r}>"


class AttributeOption(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One value of a variant axis."""

    __tablename__ = "attribute_options"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_attribute_options_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "attribute_id"],
            [f"{_S}.attributes.tenant_id", f"{_S}.attributes.organization_id", f"{_S}.attributes.id"],
            name="fk_attribute_options_attribute", ondelete="CASCADE",
        ),
        # Target of the (attribute_id, option_id) composite FK on item_attribute_values (phase 2):
        # an item can never carry a "Volume" axis with a "Flavour" option.
        UniqueConstraint("attribute_id", "id", name="uq_attribute_options_attribute_id"),
        CheckConstraint("btrim(value) <> ''", name="ck_attribute_options_value_not_blank"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_attribute_options_status"),
        Index("uq_attribute_options_value", "attribute_id", "value_normalized",
              unique=True, postgresql_where=_LIVE),
        {"schema": _S, "comment": "Values of a variant axis."},
    )

    attribute_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_normalized: Mapped[str | None] = mapped_column(
        Text, Computed("lower(btrim(value))", persisted=True), comment="STORED; uniqueness per attribute",
    )
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), comment="Sortable number (95 for '95 ml')")
    swatch: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<AttributeOption id={self.id} attribute={self.attribute_id} value={self.value!r}>"


__all__ = ["Attribute", "AttributeOption", "ItemGroup", "PackagingType", "SalesChannel", "Unit", "UqcCode"]
