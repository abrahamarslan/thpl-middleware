"""``ItemUnit`` — the packaging hierarchy (alternate units of measure, case-pack chain).

    PCS (base, factor 1) ← BTL contains 10 PCS (10) ← BOX contains 12 BTL (120) ← CTN contains 8 BOX (960)

Chained: each level names the level it CONTAINS; ``base_factor`` is cached by the trigger
``catalogue.guard_item_unit`` (never written by the application — it is recomputed and enforced in the
database). The structural columns (``unit_id``, ``is_base``, ``contents_item_unit_id``, ``contents_qty``,
``item_id``) are IMMUTABLE: a re-spec retires the level (``valid_to``) and creates a new one, so the chain is
acyclic by construction and every historic document line keeps the factor it was sold at.

Stock is always booked in the base unit; levels never hold stock. Loaders: ``lazy="raise"``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.catalogue.enums import CATALOGUE_SCHEMA, MasterStatus, values
from app.modules.catalogue.model.reference import PackagingType, Unit

_S = CATALOGUE_SCHEMA
_MONEY = Numeric(18, 6)
_QTY = Numeric(18, 6)


def _unit_fk(column: str, name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "organization_id", column],
        [f"{_S}.units.tenant_id", f"{_S}.units.organization_id", f"{_S}.units.id"],
        name=f"fk_item_units_{name}", ondelete="RESTRICT",
    )


class ItemUnit(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One level of an item's packaging hierarchy."""

    __tablename__ = "item_units"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_item_units_scope_id"),
        # target of every (item_id, item_unit_id) composite FK: a level of THIS item
        UniqueConstraint("item_id", "id", name="uq_item_units_item_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "item_id"],
            [f"{_S}.items.tenant_id", f"{_S}.items.organization_id", f"{_S}.items.id"],
            name="fk_item_units_item", ondelete="CASCADE",
        ),
        _unit_fk("unit_id", "unit"),
        ForeignKeyConstraint(["item_id", "contents_item_unit_id"], [f"{_S}.item_units.item_id", f"{_S}.item_units.id"],
                             name="fk_item_units_contents", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "packaging_type_id"],
            [f"{_S}.packaging_types.tenant_id", f"{_S}.packaging_types.organization_id", f"{_S}.packaging_types.id"],
            name="fk_item_units_packaging_type", ondelete="RESTRICT",
        ),
        _unit_fk("weight_unit_id", "weight_unit"),
        _unit_fk("dimension_unit_id", "dimension_unit"),
        CheckConstraint(
            "(is_base AND contents_item_unit_id IS NULL AND contents_qty IS NULL AND base_factor = 1) "
            "OR (NOT is_base AND contents_item_unit_id IS NOT NULL AND contents_qty > 0 AND base_factor > 0)",
            name="ck_item_units_shape"),
        CheckConstraint("contents_item_unit_id IS NULL OR contents_item_unit_id <> id", name="ck_item_units_no_self_contents"),
        CheckConstraint("(min_order_qty IS NULL OR min_order_qty > 0) AND (order_multiple IS NULL OR order_multiple > 0)",
                        name="ck_item_units_order"),
        CheckConstraint("(sales_rate IS NULL OR sales_rate >= 0) AND (purchase_rate IS NULL OR purchase_rate >= 0) "
                        "AND (mrp IS NULL OR mrp >= 0)", name="ck_item_units_rates"),
        CheckConstraint("(gross_weight IS NULL OR gross_weight >= 0) AND (length IS NULL OR length >= 0) "
                        "AND (width IS NULL OR width >= 0) AND (height IS NULL OR height >= 0)",
                        name="ck_item_units_physical"),
        CheckConstraint("NOT is_default_sales OR is_sellable", name="ck_item_units_default_sellable"),
        CheckConstraint("NOT is_default_purchase OR is_purchasable", name="ck_item_units_default_purchasable"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_item_units_window"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_item_units_status"),
        Index("uq_item_units_current", "item_id", "unit_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL")),
        Index("uq_item_units_base", "item_id", unique=True, postgresql_where=text("deleted_at IS NULL AND is_base")),
        Index("uq_item_units_default_sales", "item_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL AND is_default_sales")),
        Index("uq_item_units_default_purchase", "item_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND valid_to IS NULL AND is_default_purchase")),
        Index("ix_item_units_contents", "contents_item_unit_id", postgresql_where=text("contents_item_unit_id IS NOT NULL")),
        {"schema": _S,
         "comment": "Per-item packaging hierarchy (alternate UoM): each level contains N of another level of the same "
                    "item; base_factor cached. Structure immutable; changes retire and replace."},
    )

    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    contents_item_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    contents_qty: Mapped[Decimal | None] = mapped_column(
        _QTY, comment="1 of this level = contents_qty of contents_item_unit_id. Immutable.")
    base_factor: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False, default=Decimal(1),
        comment="1 of this level = base_factor base units. Trigger-maintained; documents snapshot it.")
    label: Mapped[str | None] = mapped_column(Text)
    packaging_type_id: Mapped[int | None] = mapped_column(BigInteger)
    is_sellable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_purchasable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_default_sales: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    is_default_purchase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    allow_break: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="May a sealed pack of this level be opened to sell its contents loose (regulated SKUs: false).")
    min_order_qty: Mapped[Decimal | None] = mapped_column(_QTY)
    order_multiple: Mapped[Decimal | None] = mapped_column(_QTY)
    sales_rate: Mapped[Decimal | None] = mapped_column(_MONEY)
    purchase_rate: Mapped[Decimal | None] = mapped_column(_MONEY)
    mrp: Mapped[Decimal | None] = mapped_column(_MONEY)
    derive_price: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="false (default, the AUoM rule): a non-base level is sellable only with an explicit price (price list "
                "entry or sales_rate) — never silently prorated. true: fall back to items.sales_rate x base_factor. "
                "Ignored on the base level.")
    gross_weight: Mapped[Decimal | None] = mapped_column(_QTY)
    weight_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    length: Mapped[Decimal | None] = mapped_column(_QTY)
    width: Mapped[Decimal | None] = mapped_column(_QTY)
    height: Mapped[Decimal | None] = mapped_column(_QTY)
    dimension_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    special_instructions: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False, default=dt.date.today, server_default=text("CURRENT_DATE"))
    valid_to: Mapped[dt.date | None] = mapped_column(Date)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Reserved for a Zoho unit-conversion id if probe P0.9 finds one; Zoho knows only the base unit today.")

    unit: Mapped[Unit] = relationship(Unit, primaryjoin="foreign(ItemUnit.unit_id) == Unit.id", viewonly=True, lazy="raise")
    packaging_type: Mapped[PackagingType | None] = relationship(
        PackagingType, primaryjoin="foreign(ItemUnit.packaging_type_id) == PackagingType.id", viewonly=True, lazy="raise")

    @property
    def is_current(self) -> bool:
        return self.valid_to is None or self.valid_to > dt.date.today()

    def __repr__(self) -> str:
        return f"<ItemUnit id={self.id} item={self.item_id} unit={self.unit_id} factor={self.base_factor}>"


__all__ = ["ItemUnit"]
