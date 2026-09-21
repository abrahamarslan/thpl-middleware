"""Transport schemas for currencies (read-only mirror)."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CurrencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None = None
    currency_code: str | None = None
    currency_name: str | None = None
    currency_symbol: str | None = None
    currency_format: str | None = None
    price_precision: int | None = None
    is_base_currency: bool | None = None
    exchange_rate: Decimal | None = None
    effective_date: date | None = None
    synced_at: datetime | None = None
