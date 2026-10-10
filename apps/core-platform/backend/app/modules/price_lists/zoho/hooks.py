"""Apply hook for the Zoho Books price-lists adapter (Zoho endpoint ``/pricebooks``).

``post_upsert`` runs after the price list row is written (it has its id). It owns what the field
map cannot express:

  * **the base-currency blank** — Zoho sends ``currency_id: ""`` for a list priced in the
    organization's base currency. The reference planner skips a blank id (it never writes NULL),
    so a list that moved to the base currency would keep its old currency without this.
  * **the items and brackets** — Zoho's ``pricebook_items`` exists only in the DETAIL document. It
    is projected as a replace-set: matched rows are updated in place (only changed columns, so
    ``row_version`` moves only on real change), new rows inserted, rows that left the list
    SOFT-deleted with ``deleted_reason='zoho:removed_from_price_list'``. A payload WITHOUT the key
    (a list row, index phase of ``index_then_detail``) changes nothing — absence is not emptiness.

Matching keys (verified live, 2026-10-08):

    item     Zoho ``item_id`` within the list (a volume item has NO pricebook_item_id)
    bracket  Zoho ``price_brackets[].pricebook_item_id`` (unique per bracket); a bracket without
             one falls back to its position among the item's unmatched brackets

The whole projection runs inside the record's savepoint: a malformed item fails the record (the
list and every child roll back together) and the run's failure journal names it.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.modules.price_lists.enums import PRICE_LISTS_MODULE
from app.modules.price_lists.model import PriceList, PriceListItem, PriceListItemBracket
from app.modules.sync.translation import CODECS

logger = structlog.get_logger("app.price_lists.zoho")

MODULE = PRICE_LISTS_MODULE
REMOVED_REASON = "zoho:removed_from_price_list"

_dec, _bool, _str = CODECS["decimal"].decode, CODECS["bool"].decode, CODECS["str"].decode


async def after_price_list_upsert(row: PriceList, payload: dict) -> None:
    db = async_object_session(row)
    if db is None or row.id is None:
        return
    if "currency_id" in payload and not str(payload.get("currency_id") or "").strip() and row.currency_id is not None:
        row.currency_id = None
    if "pricebook_items" not in payload:
        return
    counts = await project_items(db, row, payload.get("pricebook_items") or [])
    if any(counts.values()):
        logger.info("price_lists.zoho.items_projected", price_list_id=row.id, zoho_id=row.zoho_id, **counts)


# ── projection ──────────────────────────────────────────────────────────────


def _item_values(item: dict, position: int) -> dict[str, Any]:
    return {
        "item_name": _str(item.get("name")),
        "zoho_id": _str(item.get("pricebook_item_id")),
        "rate": _dec(item.get("pricebook_rate")),
        "discount": _str(item.get("pricebook_discount")),
        "can_be_sold": _bool(item.get("can_be_sold")),
        "can_be_purchased": _bool(item.get("can_be_purchased")),
        "position": position,
    }


def _bracket_values(bracket: dict, position: int) -> dict[str, Any]:
    return {
        "zoho_id": _str(bracket.get("pricebook_item_id")),
        "start_quantity": _dec(bracket.get("start_quantity")),
        "end_quantity": _dec(bracket.get("end_quantity")),          # "" = open-ended → NULL
        "rate": _dec(bracket.get("pricebook_rate")),
        "discount": _str(bracket.get("pricebook_discount")),
        "position": position,
    }


def _assign(obj: Any, values: dict[str, Any]) -> bool:
    """Set only what differs (Decimal('12.50') == Decimal('12.5') is no change)."""
    changed = False
    for column, value in values.items():
        current = getattr(obj, column)
        same = (current == value) if not (isinstance(current, Decimal) and isinstance(value, Decimal)) \
            else current.compare(value) == 0
        if not same:
            setattr(obj, column, value)
            changed = True
    return changed


def _retire(rows: Iterable[Any]) -> int:
    n = 0
    for obj in rows:
        obj.soft_delete(reason=REMOVED_REASON)
        n += 1
    return n


async def project_items(db: AsyncSession, price_list: PriceList, items: list[dict]) -> dict[str, int]:
    """Make the list's live items and brackets equal ``items`` (Zoho's ``pricebook_items``)."""
    counts = {"items_added": 0, "items_updated": 0, "items_removed": 0,
              "brackets_added": 0, "brackets_updated": 0, "brackets_removed": 0}
    scope = {"tenant_id": price_list.tenant_id, "organization_id": price_list.organization_id}

    existing_items = (await db.scalars(
        select(PriceListItem).where(PriceListItem.price_list_id == price_list.id)
    )).all()
    by_item = {obj.item_zoho_id: obj for obj in existing_items}
    existing_brackets: dict[int, list[PriceListItemBracket]] = {}
    if existing_items:
        for bracket in (await db.scalars(
            select(PriceListItemBracket)
            .where(PriceListItemBracket.price_list_item_id.in_([obj.id for obj in existing_items]))
            .order_by(PriceListItemBracket.position, PriceListItemBracket.id)
        )).all():
            existing_brackets.setdefault(bracket.price_list_item_id, []).append(bracket)

    # Items first: new ones need their id before their brackets can point at them.
    kept: dict[str, tuple[PriceListItem, list[dict]]] = {}
    for position, item in enumerate(items):
        item_zoho_id = _str(item.get("item_id"))
        if item_zoho_id is None:
            raise ValueError(f"price list {price_list.zoho_id}: item at position {position} has no item_id")
        if item_zoho_id in kept:
            # Zoho lists an item once per list; a repeat would violate uq_price_list_items_list_item.
            logger.warning("price_lists.zoho.duplicate_item", price_list_id=price_list.id, item_id=item_zoho_id,
                           action="kept the first occurrence")
            continue
        values = _item_values(item, position)
        obj = by_item.get(item_zoho_id)
        if obj is None:
            obj = PriceListItem(**scope, price_list_id=price_list.id, item_zoho_id=item_zoho_id, **values)
            db.add(obj)
            counts["items_added"] += 1
        elif _assign(obj, values):
            counts["items_updated"] += 1
        kept[item_zoho_id] = (obj, item.get("price_brackets") or [])

    leaving = [obj for key, obj in by_item.items() if key not in kept]
    for obj in leaving:
        counts["brackets_removed"] += _retire(existing_brackets.get(obj.id, []))
    counts["items_removed"] = _retire(leaving)
    await db.flush()

    for obj, brackets in kept.values():
        stored = existing_brackets.get(obj.id, [])
        incoming_ids = {_str(x.get("pricebook_item_id")) for x in brackets}
        by_zoho = {b.zoho_id: b for b in stored if b.zoho_id}
        unmatched = [b for b in stored if not b.zoho_id or b.zoho_id not in incoming_ids]
        used: set[int] = set()
        for position, raw in enumerate(brackets):
            values = _bracket_values(raw, position)
            target = by_zoho.get(values["zoho_id"]) if values["zoho_id"] else None
            if target is None and unmatched:
                target = unmatched.pop(0)
            if target is None:
                db.add(PriceListItemBracket(**scope, price_list_item_id=obj.id, **values))
                counts["brackets_added"] += 1
                continue
            used.add(id(target))
            if _assign(target, values):
                counts["brackets_updated"] += 1
        counts["brackets_removed"] += _retire(b for b in stored if id(b) not in used)
    await db.flush()
    return counts


__all__ = ["MODULE", "REMOVED_REASON", "after_price_list_upsert", "project_items"]
