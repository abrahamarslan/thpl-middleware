"""Variant templates: ``Product`` ("Dabur Almond Hair Oil") whose items are the sellable SKUs (50 ml,
95 ml…), and ``ProductAttribute`` — the product's variant axes (Zoho supports three: attribute_name1..3).

A product is OPTIONAL decoration above items (``items.product_id`` may be NULL). Zoho Inventory's "item
group" (/itemgroups) maps here; the Zoho spelling stays on the Zoho side of the field map (the price-lists
naming rule). Loaders: every relationship ``lazy="raise"``; read axes with an explicit query (crud).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.catalogue.enums import CATALOGUE_SCHEMA, MasterStatus, values
from app.modules.comments.mixins import HasCommentsMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.media.mixins import HasMediaMixin
from app.modules.tags.mixins import HasTagsMixin

_S = CATALOGUE_SCHEMA
_LIVE = text("deleted_at IS NULL")


def _scope_fk(table: str, column: str, target: str, *, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "organization_id", column],
        [f"{target}.tenant_id", f"{target}.organization_id", f"{target}.id"],
        name=f"fk_{table}_{column.removesuffix('_id')}", ondelete=ondelete,
    )


class Product(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasTagsMixin, HasDocumentsMixin, HasMediaMixin, HasCommentsMixin,
    SoftDeleteFilteredMixin, Base,
):
    """A variant template grouping sellable items."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_products_scope_id"),
        _scope_fk("products", "brand_id", "core.brands"),
        _scope_fk("products", "manufacturer_id", "core.manufacturers"),
        _scope_fk("products", "item_group_id", f"{_S}.item_groups"),
        _scope_fk("products", "default_unit_id", f"{_S}.units"),
        CheckConstraint("btrim(name) <> ''", name="ck_products_name_not_blank"),
        CheckConstraint("slug IS NULL OR slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_products_slug"),
        CheckConstraint(f"status IN ({values(MasterStatus)})", name="ck_products_status"),
        Index("uq_products_scope_slug", "tenant_id", "organization_id", "slug", unique=True,
              postgresql_where=text("deleted_at IS NULL AND slug IS NOT NULL")),
        Index("uq_products_scope_code", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL AND code IS NOT NULL")),
        Index("uq_products_zoho_id", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        Index("ix_products_name_trgm", "name_normalized", postgresql_using="gin",
              postgresql_ops={"name_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE),
        Index("ix_products_brand", "brand_id", postgresql_where=_LIVE),
        {"schema": _S, "comment": "Variant template grouping sellable items (Zoho Inventory item group). Optional per item."},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_normalized: Mapped[str | None] = mapped_column(
        Text, Computed(r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))", persisted=True),
    )
    slug: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    brand_id: Mapped[int | None] = mapped_column(BigInteger)
    manufacturer_id: Mapped[int | None] = mapped_column(BigInteger)
    item_group_id: Mapped[int | None] = mapped_column(BigInteger)
    default_unit_id: Mapped[int | None] = mapped_column(BigInteger)
    zoho_id: Mapped[str | None] = mapped_column(String(50))

    def __repr__(self) -> str:
        return f"<Product id={self.id} name={self.name!r}>"


class ProductAttribute(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """One variant axis of a product (position 1..10; Zoho uses 1..3)."""

    __tablename__ = "product_attributes"
    __table_args__ = (
        _scope_fk("product_attributes", "product_id", f"{_S}.products", ondelete="CASCADE"),
        _scope_fk("product_attributes", "attribute_id", f"{_S}.attributes"),
        CheckConstraint("position BETWEEN 1 AND 10", name="ck_product_attributes_position"),
        Index("uq_product_attributes_axis", "product_id", "attribute_id", unique=True, postgresql_where=_LIVE),
        Index("uq_product_attributes_position", "product_id", "position", unique=True, postgresql_where=_LIVE),
        {"schema": _S, "comment": "The variant axes of a product (Zoho supports three: attribute_name1..3)."},
    )

    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attribute_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))


__all__ = ["Product", "ProductAttribute"]
