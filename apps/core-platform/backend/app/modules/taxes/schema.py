"""Transport schemas for taxes (read-only mirror)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None = None
    tax_name: str | None = None
    tax_percentage: Decimal | None = None
    tax_type: str | None = None
    tax_specific_type: str | None = None
    tax_authority_name: str | None = None
    is_value_added: bool | None = None
    is_default_tax: bool | None = None
    country_code: str | None = None
    synced_at: datetime | None = None
