"""Vocabularies of the ``pricing`` schema (CHECKs are built FROM these, so they cannot drift).

Our name is **price list**; Zoho's API calls the same thing a *pricebook* (``/pricebooks``,
``pricebook_id``, ``pricebook_items``). Zoho's spelling appears only where we read Zoho's payload
(``zoho/``); every table, column, class and route here says price list.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import values

#: Postgres schema holding price lists.
PRICING_SCHEMA = "pricing"

#: The crosswalk module key (``sync.sync_records.module``) — renamed from ``pricebooks`` in migration
#: ``20261008_1600_7c3e91a05d24``.
PRICE_LISTS_MODULE = "price_lists"


class PriceListType(enum.StrEnum):
    """Zoho ``pricebook_type`` (documented closed set)."""

    PER_ITEM = "per_item"                    # explicit rates per item (unit) or per quantity bracket (volume)
    FIXED_PERCENTAGE = "fixed_percentage"    # markup / markdown over the item's own rate


class PricingScheme(enum.StrEnum):
    """Zoho ``pricing_scheme`` — only meaningful for ``per_item`` lists (``""`` → NULL otherwise)."""

    UNIT = "unit"
    VOLUME = "volume"


class PriceListUsage(enum.StrEnum):
    """Zoho ``sales_or_purchase_type``."""

    SALES = "sales"
    PURCHASES = "purchases"


class PriceListStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class RoundingType(enum.StrEnum):
    """Zoho ``rounding_type`` — the 16 keys Zoho's own price-list form offers (captured response, 2026-10-08).

    Stored as text WITHOUT a CHECK: the documented list is shorter (and misspells ``round_to_dollor``) than
    what Zoho actually sends, so a CHECK would turn Zoho's next key into a failed record. The quote
    calculator refuses a key it does not know instead of guessing.
    """

    NO_ROUNDING = "no_rounding"
    ONE_CENT = "round_to_one_cent"
    TWO_CENTS = "round_to_two_cents"
    NICKEL = "round_to_nickel"
    DIME = "round_to_dime"
    QUARTER = "round_to_quarter"
    HALF_DOLLAR = "round_to_half_dollar"
    DOLLAR = "round_to_dollar"
    DOLLAR_MINUS_01 = "round_to_dollar_minus_01"
    DOLLAR_MINUS_02 = "round_to_dollar_minus_02"
    DOLLAR_MINUS_05 = "round_to_dollar_minus_05"
    DOLLAR_MINUS_11 = "round_to_dollar_minus_11"
    HALF_DOLLAR_MINUS_01 = "round_to_half_dollar_minus_01"
    HALF_DOLLAR_MINUS_05 = "round_to_half_dollar_minus_05"
    DIME_MINUS_01 = "round_to_dime_minus_01"
    BASED_ON_DECIMAL = "round_based_on_decimal"


__all__ = [
    "PRICE_LISTS_MODULE",
    "PRICING_SCHEMA",
    "PriceListStatus",
    "PriceListType",
    "PriceListUsage",
    "PricingScheme",
    "RoundingType",
    "values",
]
