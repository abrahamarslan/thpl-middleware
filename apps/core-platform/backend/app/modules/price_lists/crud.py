"""Data access for price lists (crud layer — no business logic).

Organization scope is the session's (tenancy's SELECT criteria); every relationship is
``lazy="raise"`` and loaded explicitly here.
"""

from __future__ import annotations

import uuid as uuid_lib
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.price_lists.model import PriceList, PriceListItem, PriceListItemBracket


def _ref_condition(ref: str | int):
    if isinstance(ref, int) or str(ref).isdigit():
        return PriceList.id == int(ref)
    try:
        return PriceList.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        return None


async def list_price_lists(
    db: AsyncSession, *, usage: str | None = None, price_list_type: str | None = None,
    status: str | None = None, q: str | None = None, limit: int = 200, offset: int = 0,
) -> list[tuple[PriceList, int]]:
    """Price lists with their live item count, name order."""
    item_count = (
        select(func.count(PriceListItem.id))
        .where(PriceListItem.price_list_id == PriceList.id)
        .correlate(PriceList).scalar_subquery()
    )
    stmt = (select(PriceList, item_count).options(joinedload(PriceList.currency))
            .order_by(PriceList.name, PriceList.id))
    if usage:
        stmt = stmt.where(PriceList.sales_or_purchase_type == usage)
    if price_list_type:
        stmt = stmt.where(PriceList.price_list_type == price_list_type)
    if status:
        stmt = stmt.where(PriceList.status == status)
    if q:
        stmt = stmt.where(or_(PriceList.name.ilike(f"%{q.strip()}%"), PriceList.zoho_id == q.strip()))
    rows = await db.execute(stmt.limit(limit).offset(offset))
    return [(price_list, count) for price_list, count in rows.all()]


async def get_price_list(db: AsyncSession, ref: str | int, *, with_items: bool = False) -> PriceList | None:
    condition = _ref_condition(ref)
    if condition is None:
        return None
    options = [joinedload(PriceList.currency)]
    if with_items:
        options.append(selectinload(PriceList.items).selectinload(PriceListItem.brackets))
    return await db.scalar(select(PriceList).where(condition).options(*options).limit(1))


async def get_item(db: AsyncSession, price_list_id: int, item_zoho_id: str) -> PriceListItem | None:
    return await db.scalar(
        select(PriceListItem)
        .where(PriceListItem.price_list_id == price_list_id, PriceListItem.item_zoho_id == item_zoho_id)
        .options(selectinload(PriceListItem.brackets)).limit(1)
    )


async def bracket_for(db: AsyncSession, item_id: int, quantity: Decimal) -> PriceListItemBracket | None:
    """The bracket in force at ``quantity``: the highest start not above it."""
    return await db.scalar(
        select(PriceListItemBracket)
        .where(PriceListItemBracket.price_list_item_id == item_id,
               PriceListItemBracket.start_quantity <= quantity)
        .order_by(PriceListItemBracket.start_quantity.desc(), PriceListItemBracket.id.desc()).limit(1)
    )


__all__ = ["bracket_for", "get_item", "get_price_list", "list_price_lists"]
