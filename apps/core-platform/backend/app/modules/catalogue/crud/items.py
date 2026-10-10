"""Data access for items, their hierarchy and children, and products (SQL only, no business rules).

Slim lists use ``load_only``; the fat item read loads every child collection with ``selectinload``
(one query each, regardless of how many rows) and every to-one with ``joinedload``. Nothing here can
lazy-load (all relationships are ``lazy="raise"``).
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only, selectinload

from app.modules.catalogue.model import (
    Item,
    ItemComponent,
    ItemIdentifier,
    ItemMerchandising,
    ItemUnit,
    Product,
    ProductAttribute,
)

ITEM_SLIM = (
    Item.id, Item.uuid, Item.sku, Item.code, Item.name, Item.generic_name, Item.status, Item.brand_id,
    Item.item_group_id, Item.product_id, Item.base_unit_id, Item.hsn_or_sac, Item.sales_rate, Item.mrp,
    Item.track_mode, Item.can_be_sold, Item.can_be_purchased, Item.zoho_id,
)
PRODUCT_SLIM = (Product.id, Product.uuid, Product.name, Product.slug, Product.code, Product.brand_id,
                Product.item_group_id, Product.status)


def _ref_condition(model: type, ref: str):
    if str(ref).isdigit():
        return model.id == int(ref)
    try:
        return model.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        return None


def _fat_options():
    return (
        joinedload(Item.brand), joinedload(Item.manufacturer), joinedload(Item.base_unit),
        joinedload(Item.item_group), joinedload(Item.product), joinedload(Item.merchandising),
        selectinload(Item.units).joinedload(ItemUnit.unit),
        selectinload(Item.identifiers), selectinload(Item.components), selectinload(Item.channels),
        selectinload(Item.vendors), selectinload(Item.attribute_values),
    )


async def get_item(db: AsyncSession, ref: str, *, organization_id: int, fat: bool = True) -> Item | None:
    condition = _ref_condition(Item, ref)
    if condition is None:
        return None
    stmt = select(Item).where(condition, Item.organization_id == organization_id).limit(1)
    if fat:
        stmt = stmt.options(*_fat_options())
    return (await db.scalars(stmt)).unique().first()


async def get_item_by_id(db: AsyncSession, item_id: int, *, organization_id: int) -> Item | None:
    return await db.scalar(select(Item).where(Item.id == item_id, Item.organization_id == organization_id))


async def list_items(
    db: AsyncSession, *, organization_id: int, q: str | None = None, filters: dict[str, Any] | None = None,
    category_ids: list[int] | None = None, limit: int = 50, offset: int = 0,
) -> tuple[list[Item], int]:
    stmt = select(Item).where(Item.organization_id == organization_id)
    for column, value in (filters or {}).items():
        if value is not None:
            stmt = stmt.where(getattr(Item, column) == value)
    if q:
        term = q.strip()
        pattern = f"%{term.lower()}%"
        stmt = stmt.where(or_(
            Item.name_normalized.like(pattern), Item.sku_normalized == term.upper(),
            func.lower(Item.generic_name).like(pattern), Item.alias_names.any(term), Item.code == term,
        ))
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.scalars(stmt.options(load_only(*ITEM_SLIM)).order_by(Item.position, Item.name, Item.id)
                            .offset(offset).limit(limit))
    return list(rows.all()), int(total or 0)


async def find_item(db: AsyncSession, *, organization_id: int, **eq: Any) -> Item | None:
    stmt = select(Item).where(Item.organization_id == organization_id)
    for column, value in eq.items():
        stmt = stmt.where(getattr(Item, column) == value)
    return await db.scalar(stmt.limit(1))


# ── hierarchy ────────────────────────────────────────────────────────────────

async def item_levels(db: AsyncSession, item_id: int) -> list[ItemUnit]:
    rows = await db.scalars(select(ItemUnit).where(ItemUnit.item_id == item_id)
                            .options(joinedload(ItemUnit.unit))
                            .order_by(ItemUnit.base_factor.desc(), ItemUnit.id))
    return list(rows.unique().all())


async def get_level(db: AsyncSession, item_id: int, ref: str) -> ItemUnit | None:
    condition = _ref_condition(ItemUnit, ref)
    if condition is None:
        return None
    return (await db.scalars(select(ItemUnit).where(condition, ItemUnit.item_id == item_id)
                             .options(joinedload(ItemUnit.unit)))).unique().first()


async def current_level_for_unit(db: AsyncSession, item_id: int, unit_id: int) -> ItemUnit | None:
    return await db.scalar(select(ItemUnit).where(ItemUnit.item_id == item_id, ItemUnit.unit_id == unit_id,
                                                  ItemUnit.valid_to.is_(None)))


async def level_is_contained(db: AsyncSession, level_id: int) -> bool:
    return await db.scalar(select(ItemUnit.id).where(ItemUnit.contents_item_unit_id == level_id,
                                                     ItemUnit.valid_to.is_(None)).limit(1)) is not None


async def clear_level_defaults(db: AsyncSession, item_id: int, column: str, *, keep_id: int | None) -> None:
    stmt = select(ItemUnit).where(ItemUnit.item_id == item_id, getattr(ItemUnit, column).is_(True),
                                  ItemUnit.valid_to.is_(None))
    for row in (await db.scalars(stmt)).all():
        if row.id != keep_id:
            setattr(row, column, False)


# ── children ─────────────────────────────────────────────────────────────────

async def children(db: AsyncSession, model: type, item_id: int, column: str = "item_id") -> list[Any]:
    return list((await db.scalars(select(model).where(getattr(model, column) == item_id)
                                  .order_by(model.id))).all())


async def find_identifier(db: AsyncSession, organization_id: int, normalized: str) -> ItemIdentifier | None:
    return await db.scalar(select(ItemIdentifier).where(
        ItemIdentifier.organization_id == organization_id, ItemIdentifier.value_normalized == normalized,
        ItemIdentifier.kind.in_(("gtin", "ean", "upc", "isbn", "barcode"))).limit(1))


async def lookup_identifier(db: AsyncSession, organization_id: int, normalized: str) -> ItemIdentifier | None:
    """Scannable kinds first (unique), then any kind (mpn / part numbers may repeat — first match)."""
    found = await find_identifier(db, organization_id, normalized)
    if found is not None:
        return found
    return await db.scalar(select(ItemIdentifier).where(
        ItemIdentifier.organization_id == organization_id, ItemIdentifier.value_normalized == normalized)
        .order_by(ItemIdentifier.id).limit(1))


async def get_identifier(db: AsyncSession, item_id: int, ref: str) -> ItemIdentifier | None:
    condition = _ref_condition(ItemIdentifier, ref)
    if condition is None:
        return None
    return await db.scalar(select(ItemIdentifier).where(condition, ItemIdentifier.item_id == item_id))


async def merchandising(db: AsyncSession, item_id: int) -> ItemMerchandising | None:
    return await db.scalar(select(ItemMerchandising).where(ItemMerchandising.item_id == item_id))


async def is_component_somewhere(db: AsyncSession, item_id: int) -> bool:
    return await db.scalar(select(ItemComponent.id).where(ItemComponent.component_item_id == item_id,
                                                          ItemComponent.valid_to.is_(None)).limit(1)) is not None


# ── products ─────────────────────────────────────────────────────────────────

async def get_product(db: AsyncSession, ref: str, *, organization_id: int) -> Product | None:
    condition = _ref_condition(Product, ref)
    if condition is None:
        return None
    return await db.scalar(select(Product).where(condition, Product.organization_id == organization_id))


async def list_products(db: AsyncSession, *, organization_id: int, q: str | None = None, brand_id: int | None = None,
                        limit: int = 50, offset: int = 0) -> tuple[list[Product], int]:
    stmt = select(Product).where(Product.organization_id == organization_id)
    if q:
        stmt = stmt.where(Product.name_normalized.like(f"%{q.strip().lower()}%"))
    if brand_id is not None:
        stmt = stmt.where(Product.brand_id == brand_id)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = await db.scalars(stmt.options(load_only(*PRODUCT_SLIM)).order_by(Product.name, Product.id)
                            .offset(offset).limit(limit))
    return list(rows.all()), int(total or 0)


async def product_axes(db: AsyncSession, product_id: int) -> list[ProductAttribute]:
    return list((await db.scalars(select(ProductAttribute).where(ProductAttribute.product_id == product_id)
                                  .order_by(ProductAttribute.position))).all())


async def product_variants(db: AsyncSession, product_id: int) -> list[Item]:
    return list((await db.scalars(select(Item).where(Item.product_id == product_id).options(load_only(*ITEM_SLIM))
                                  .order_by(Item.name, Item.id))).all())


async def find_product(db: AsyncSession, *, organization_id: int, **eq: Any) -> Product | None:
    stmt = select(Product).where(Product.organization_id == organization_id)
    for column, value in eq.items():
        stmt = stmt.where(getattr(Product, column) == value)
    return await db.scalar(stmt.limit(1))


# ── data quality ─────────────────────────────────────────────────────────────

async def data_quality(db: AsyncSession, organization_id: int) -> dict[str, int]:
    live = Item.organization_id == organization_id
    no_base = await db.scalar(select(func.count()).where(live, Item.base_unit_id.is_(None)))
    no_hsn = await db.scalar(select(func.count()).where(live, Item.hsn_or_sac.is_(None), Item.product_type == "goods"))
    from app.modules.taxes.assignment import TaxAssignment

    taxed = select(TaxAssignment.owner_id).where(TaxAssignment.owner_type_code == "item")
    no_tax = await db.scalar(select(func.count()).where(live, Item.is_taxable.is_not(False), Item.id.not_in(taxed),
                                                        or_(Item.product_type.is_(None), Item.product_type == "goods")))
    batch_no_rule = await db.scalar(select(func.count()).where(live, Item.track_mode != "none",
                                                               Item.expiry_tracked.is_(True),
                                                               Item.shelf_life_days.is_(None)))
    unpriced = await db.scalar(
        select(func.count()).select_from(ItemUnit).join(Item, Item.id == ItemUnit.item_id)
        .where(live, ItemUnit.is_base.is_(False), ItemUnit.valid_to.is_(None), ItemUnit.is_sellable.is_(True),
               ItemUnit.derive_price.is_(False), ItemUnit.sales_rate.is_(None)))
    return {"items_without_base_unit": int(no_base or 0), "items_without_hsn": int(no_hsn or 0),
            "goods_without_tax": int(no_tax or 0), "batch_items_without_expiry_rule": int(batch_no_rule or 0),
            "levels_without_price": int(unpriced or 0)}



__all__ = [
    "ITEM_SLIM", "children", "clear_level_defaults", "current_level_for_unit", "data_quality", "find_identifier",
    "find_item", "find_product", "get_identifier", "get_item", "get_item_by_id", "get_level", "get_product",
    "is_component_somewhere", "item_levels", "level_is_contained", "list_items", "list_products",
    "lookup_identifier", "merchandising", "product_axes", "product_variants",
]
