"""Response models of the price lists API (read-only: Zoho masters price lists)."""

from __future__ import annotations

import uuid as uuid_lib
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PriceListSlimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid_lib.UUID
    name: str
    price_list_type: str
    pricing_scheme: str | None
    sales_or_purchase_type: str
    status: str
    is_default: bool | None
    percentage: Decimal | None
    is_increase: bool | None
    currency_code: str | None = None
    item_count: int = 0
    zoho_id: str | None


class PriceListItemBracketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None
    start_quantity: Decimal | None
    end_quantity: Decimal | None
    rate: Decimal | None
    discount: str | None


class PriceListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_zoho_id: str
    item_name: str | None
    zoho_id: str | None
    rate: Decimal | None
    discount: str | None
    can_be_sold: bool | None
    can_be_purchased: bool | None
    position: int
    brackets: list[PriceListItemBracketOut] = []


class PriceListOut(PriceListSlimOut):
    organization_id: int
    description: str | None
    rate: Decimal | None
    rounding_type: str | None
    decimal_place: int | None
    currency_id: int | None
    items: list[PriceListItemOut] = []


class PriceQuoteOut(BaseModel):
    price_list_id: int
    item_id: str
    quantity: Decimal
    rate: Decimal
    basis: str
    base_rate: Decimal | None
    bracket_start: Decimal | None
    bracket_end: Decimal | None
    between_brackets: bool
    price_list_active: bool
    discount: str | None


__all__ = ["PriceListItemBracketOut", "PriceListItemOut", "PriceListOut", "PriceListSlimOut", "PriceQuoteOut"]
