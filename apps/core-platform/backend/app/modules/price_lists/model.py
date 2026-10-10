"""Price lists (Zoho calls them "pricebooks") — organization-scoped, Zoho-synced through the crosswalk.

    PriceList              one price list of one organization (header)
    PriceListItem          an item's entry in a ``per_item`` list (unit rate, or the parent of its brackets)
    PriceListItemBracket   one quantity bracket of a ``volume`` list's item

Zoho provenance. ``PriceList`` is a crosswalk module (module ``price_lists``, Zoho endpoint
``/pricebooks``): identity, the gate's fence and hash and the raw document live in
``sync.sync_records``; the row carries business columns plus the engine-maintained ``zoho_id`` echo.
The children are projected from the DETAIL document by the adapter's hook (``zoho/hooks.py``); each
keeps Zoho's own id where Zoho gives one:

    PriceListItem.zoho_id         Zoho ``pricebook_item_id`` — present for UNIT-scheme items only
                                  (verified live: a volume item has none; its brackets do)
    PriceListItemBracket.zoho_id  Zoho ``price_brackets[].pricebook_item_id`` — unique per bracket
                                  despite the name (the docs call it the parent item's id; the live
                                  data disagrees: 29 brackets, 29 distinct ids)

Items are referenced by Zoho's ``item_id`` (``item_zoho_id``): there is no items module yet. When it
lands, ``item_id`` (a real FK) is added and linked through the crosswalk; the Zoho id stays as the
source reference.

Children are SOFT-deleted when they leave the list (never ``session.delete``): a price that was in
force is evidence, and the platform's delete doctrine applies here as everywhere.

Scoping: ``OrgEntityMixin`` everywhere; children pin their parent's tenant AND organization with
composite FKs, so a bracket can never hang under another organization's item.

Loaders (stated): ``PriceList.items`` / ``PriceListItem.brackets`` are ``lazy="raise"`` and read with
explicit ``selectinload`` (crud.get_price_list); every to-one relationship is ``lazy="raise"``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
# FK target of currency_id: mapped wherever a price list is (a seeder or task importing only this module).
from app.modules.currencies import model as _currency_model  # noqa: F401
from app.modules.price_lists.enums import (
    PRICING_SCHEMA,
    PriceListStatus,
    PriceListType,
    PriceListUsage,
    PricingScheme,
    values,
)

_LIVE = text("deleted_at IS NULL")
_MONEY = Numeric(18, 6)


class PriceList(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One price list of one organization."""

    __tablename__ = "price_lists"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_price_lists_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "currency_id"], ["currency.currencies.tenant_id", "currency.currencies.id"],
            name="fk_price_lists_currency", ondelete="RESTRICT",
        ),
        CheckConstraint(f"price_list_type IN ({values(PriceListType)})", name="ck_price_lists_type"),
        CheckConstraint(f"sales_or_purchase_type IN ({values(PriceListUsage)})", name="ck_price_lists_usage"),
        CheckConstraint(f"pricing_scheme IS NULL OR pricing_scheme IN ({values(PricingScheme)})",
                        name="ck_price_lists_scheme"),
        CheckConstraint(f"status IN ({values(PriceListStatus)})", name="ck_price_lists_status"),
        CheckConstraint("btrim(name) <> ''", name="ck_price_lists_name_not_blank"),
        CheckConstraint("decimal_place IS NULL OR decimal_place BETWEEN 0 AND 10",
                        name="ck_price_lists_decimal_place"),
        Index("uq_price_lists_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_price_lists_org_usage_status", "organization_id", "sales_or_purchase_type", "status",
              postgresql_where=_LIVE),
        Index("ix_price_lists_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"},
              postgresql_where=_LIVE),
        {"schema": PRICING_SCHEMA,
         "comment": "Price lists of one organization (Zoho: pricebooks); Zoho crosswalk module price_lists."},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_list_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="per_item | fixed_percentage (Zoho pricebook_type)",
    )
    sales_or_purchase_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="sales | purchases")
    pricing_scheme: Mapped[str | None] = mapped_column(
        String(16), comment="unit | volume (per_item lists); NULL for fixed_percentage (Zoho sends \"\")",
    )
    percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), comment="fixed_percentage: the markup (is_increase) or markdown percent",
    )
    rate: Mapped[Decimal | None] = mapped_column(
        _MONEY, comment="List-level rate as Zoho sends it (Zoho pricebook_rate; observed = percentage)",
    )
    is_increase: Mapped[bool | None] = mapped_column(Boolean, comment="true = markup, false = markdown")
    rounding_type: Mapped[str | None] = mapped_column(
        String(48), comment="Zoho rounding key (no_rounding, round_to_dollar …); applied to fixed_percentage quotes",
    )
    decimal_place: Mapped[int | None] = mapped_column(SmallInteger, comment="Digits for round_based_on_decimal")
    is_default: Mapped[bool | None] = mapped_column(
        Boolean, comment="Zoho's default price list flag (DETAIL document only; NULL until the detail lands)",
    )
    currency_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="currency.currencies; NULL = the organization's base currency (Zoho sends \"\")",
    )
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Engine-maintained echo of Zoho pricebook_id (not the identity of record)",
    )

    currency: Mapped[_currency_model.Currency | None] = relationship(
        "Currency", primaryjoin="foreign(PriceList.currency_id) == Currency.id", viewonly=True, lazy="raise",
    )
    items: Mapped[list[PriceListItem]] = relationship(
        "PriceListItem", primaryjoin="and_(PriceList.id == foreign(PriceListItem.price_list_id), "
                                     "PriceListItem.deleted_at.is_(None))",
        viewonly=True, lazy="raise", order_by="(PriceListItem.position, PriceListItem.id)",
    )

    @property
    def is_active(self) -> bool:
        return self.status == PriceListStatus.ACTIVE.value

    def __repr__(self) -> str:
        return f"<PriceList id={self.id} {self.name!r} {self.price_list_type}/{self.pricing_scheme}>"


class PriceListItem(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """An item's entry in a per_item price list."""

    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_price_list_items_scope_id"),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "price_list_id"],
            [f"{PRICING_SCHEMA}.price_lists.tenant_id", f"{PRICING_SCHEMA}.price_lists.organization_id",
             f"{PRICING_SCHEMA}.price_lists.id"],
            name="fk_price_list_items_price_list", ondelete="RESTRICT",
        ),
        CheckConstraint("btrim(item_zoho_id) <> ''", name="ck_price_list_items_item_ref"),
        Index("uq_price_list_items_list_item", "price_list_id", "item_zoho_id", unique=True, postgresql_where=_LIVE),
        Index("uq_price_list_items_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_price_list_items_item", "item_zoho_id", postgresql_where=_LIVE),
        {"schema": PRICING_SCHEMA, "comment": "Items of a per_item price list (unit rate, or parent of brackets)."},
    )

    price_list_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_zoho_id: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Zoho item_id (no items module yet; an item_id FK joins it later)",
    )
    item_name: Mapped[str | None] = mapped_column(Text, comment="Item name as embedded in the price list (snapshot)")
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Zoho pricebook_item_id — present for unit-scheme items only (verified live)",
    )
    rate: Mapped[Decimal | None] = mapped_column(_MONEY, comment="Unit-scheme price of the item (Zoho pricebook_rate)")
    discount: Mapped[str | None] = mapped_column(
        Text, comment="Zoho pricebook_discount verbatim (e.g. \"5%\"); NULL when Zoho sends \"\"",
    )
    can_be_sold: Mapped[bool | None] = mapped_column(Boolean, comment="Item-master flag as embedded (snapshot)")
    can_be_purchased: Mapped[bool | None] = mapped_column(Boolean, comment="Item-master flag as embedded (snapshot)")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    brackets: Mapped[list[PriceListItemBracket]] = relationship(
        "PriceListItemBracket",
        primaryjoin="and_(PriceListItem.id == foreign(PriceListItemBracket.price_list_item_id), "
                    "PriceListItemBracket.deleted_at.is_(None))",
        viewonly=True, lazy="raise",
        order_by="(PriceListItemBracket.start_quantity, PriceListItemBracket.id)",
    )

    def __repr__(self) -> str:
        return f"<PriceListItem list={self.price_list_id} item={self.item_zoho_id} rate={self.rate}>"


class PriceListItemBracket(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One quantity bracket of a volume price list's item."""

    __tablename__ = "price_list_item_brackets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "price_list_item_id"],
            [f"{PRICING_SCHEMA}.price_list_items.tenant_id", f"{PRICING_SCHEMA}.price_list_items.organization_id",
             f"{PRICING_SCHEMA}.price_list_items.id"],
            name="fk_price_list_item_brackets_item", ondelete="RESTRICT",
        ),
        CheckConstraint("end_quantity IS NULL OR start_quantity IS NULL OR end_quantity >= start_quantity",
                        name="ck_price_list_item_brackets_range"),
        Index("uq_price_list_item_brackets_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_price_list_item_brackets_lookup", "price_list_item_id", "start_quantity", postgresql_where=_LIVE),
        {"schema": PRICING_SCHEMA, "comment": "Quantity brackets of a volume price list's item."},
    )

    price_list_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Zoho price_brackets[].pricebook_item_id — identifies the BRACKET (verified live)",
    )
    start_quantity: Mapped[Decimal | None] = mapped_column(_MONEY, comment="Inclusive lower bound")
    end_quantity: Mapped[Decimal | None] = mapped_column(
        _MONEY, comment="Upper bound; NULL = open-ended top bracket (Zoho sends \"\")",
    )
    rate: Mapped[Decimal | None] = mapped_column(_MONEY, comment="Unit price within this bracket (Zoho pricebook_rate)")
    discount: Mapped[str | None] = mapped_column(Text, comment="Zoho pricebook_discount verbatim")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return (f"<PriceListItemBracket item={self.price_list_item_id} "
                f"{self.start_quantity}-{self.end_quantity} @ {self.rate}>")


__all__ = ["PriceList", "PriceListItem", "PriceListItemBracket"]
