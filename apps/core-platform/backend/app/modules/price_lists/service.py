"""Pricing — "what does this item cost under this price list at this quantity?"

The rules, per Zoho's model (https://www.zoho.com/books/api/v3/pricelists/ + live data):

    per_item / unit     the item's ``rate`` in the list
    per_item / volume   the bracket in force: the highest ``start_quantity`` ≤ quantity. A quantity
                        above that bracket's ``end_quantity`` (Zoho's brackets are integer ranges —
                        10–19, 20–49 — so 19.5 falls in a gap) keeps that bracket and is flagged
                        ``between_brackets``
    fixed_percentage    base_rate × (100 ± percentage) / 100, then the list's rounding

An item the list does not price (not listed, or below the first bracket) falls back to the
caller's ``base_rate`` — the item's own rate, which Zoho also uses. There is no items module yet,
so the base rate is always the CALLER's input; without one such a quote is refused, never guessed.

Rounding (fixed_percentage only). Implemented where the meaning is unambiguous:
``no_rounding``, ``round_to_dollar`` (nearest whole unit, half up) and ``round_based_on_decimal``
(``decimal_place`` digits, half up). Zoho does not document the arithmetic of the other keys
(``round_to_dollar_minus_01`` …); a list using one is refused (``pricing_rounding_not_supported``)
rather than priced by a guess. The half-up choice is ours — verify against a Zoho-priced document
before relying on a .5 boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.price_lists import crud
from app.modules.price_lists.enums import PriceListType, PricingScheme, RoundingType
from app.modules.price_lists.errors import PricingError, RoundingNotSupportedError
from app.modules.price_lists.model import PriceList, PriceListItem, PriceListItemBracket

_HUNDRED = Decimal(100)
_MONEY_PLACES = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class PriceQuote:
    price_list_id: int
    item_id: str
    quantity: Decimal
    rate: Decimal
    basis: str                      # unit_rate | volume_bracket | percentage | base_rate_fallback
    base_rate: Decimal | None = None
    bracket_start: Decimal | None = None
    bracket_end: Decimal | None = None
    between_brackets: bool = False
    price_list_active: bool = True
    discount: str | None = None     # Zoho's discount string, verbatim, when the entry carries one

    def as_dict(self) -> dict:
        return asdict(self)


def apply_rounding(value: Decimal, rounding_type: str | None, decimal_place: int | None) -> Decimal:
    key = rounding_type or RoundingType.NO_ROUNDING.value
    if key == RoundingType.NO_ROUNDING:
        return value.quantize(_MONEY_PLACES, rounding=ROUND_HALF_UP)
    if key == RoundingType.DOLLAR:
        return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    if key == RoundingType.BASED_ON_DECIMAL:
        return value.quantize(Decimal(1).scaleb(-(decimal_place or 0)), rounding=ROUND_HALF_UP)
    raise RoundingNotSupportedError(f"Rounding '{key}' is not supported for quotes yet")


def compute_price(
    price_list: PriceList, item_id: str, quantity: Decimal, *, base_rate: Decimal | None,
    entry: PriceListItem | None, bracket: PriceListItemBracket | None,
) -> PriceQuote:
    """Pure: the quote from already-loaded rows (``entry`` = the item's row in the list, if any)."""
    if quantity <= 0:
        raise PricingError("Quantity must be positive")
    common = {"price_list_id": price_list.id, "item_id": item_id, "quantity": quantity, "base_rate": base_rate,
              "price_list_active": price_list.is_active}

    if price_list.price_list_type == PriceListType.FIXED_PERCENTAGE:
        if base_rate is None:
            raise PricingError("A fixed-percentage price list needs the item's base_rate")
        percentage = price_list.percentage or Decimal(0)
        factor = (_HUNDRED + percentage) if price_list.is_increase else (_HUNDRED - percentage)
        rate = apply_rounding(base_rate * factor / _HUNDRED, price_list.rounding_type, price_list.decimal_place)
        if rate < 0:
            raise PricingError(f"A {percentage}% markdown makes the price negative")
        return PriceQuote(**common, rate=rate, basis="percentage")

    volume = price_list.pricing_scheme == PricingScheme.VOLUME
    if entry is not None and volume and bracket is not None and bracket.rate is not None:
        between = bracket.end_quantity is not None and quantity > bracket.end_quantity
        return PriceQuote(**common, rate=bracket.rate, basis="volume_bracket",
                          bracket_start=bracket.start_quantity, bracket_end=bracket.end_quantity,
                          between_brackets=between, discount=bracket.discount)
    if entry is not None and not volume and entry.rate is not None:
        return PriceQuote(**common, rate=entry.rate, basis="unit_rate", discount=entry.discount)

    if base_rate is None:
        reason = "is not in this price list" if entry is None else "is below this price list's first bracket"
        raise PricingError(f"Item {item_id} {reason}; pass base_rate to fall back to the item's own rate")
    return PriceQuote(**common, rate=base_rate, basis="base_rate_fallback")


async def get_price_list(db: AsyncSession, ref: str | int, *, with_items: bool = False) -> PriceList:
    price_list = await crud.get_price_list(db, ref, with_items=with_items)
    if price_list is None:
        raise NotFoundError(f"Price list '{ref}' not found")
    return price_list


async def quote(
    db: AsyncSession, ref: str | int, *, item_id: str, quantity: Decimal, base_rate: Decimal | None = None,
) -> PriceQuote:
    price_list = await get_price_list(db, ref)
    entry = bracket = None
    if price_list.price_list_type == PriceListType.PER_ITEM:
        entry = await crud.get_item(db, price_list.id, item_id)
        if entry is not None and price_list.pricing_scheme == PricingScheme.VOLUME and quantity > 0:
            bracket = await crud.bracket_for(db, entry.id, quantity)
    return compute_price(price_list, item_id, quantity, base_rate=base_rate, entry=entry, bracket=bracket)


__all__ = ["PriceQuote", "apply_rounding", "compute_price", "get_price_list", "quote"]
