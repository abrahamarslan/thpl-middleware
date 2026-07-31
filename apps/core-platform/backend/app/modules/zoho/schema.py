"""Transport schemas for Zoho endpoints (schema layer)."""

from pydantic import BaseModel, Field


class ZohoItem(BaseModel):
    item_id: str
    name: str
    rate: float = 0.0
    stock_on_hand: float | None = Field(default=None, description="Available stock from Zoho")
    sku: str | None = None
    status: str | None = None


class SyncStateOut(BaseModel):
    entity: str
    status: str
    last_synced_at: str | None = None
    detail: str | None = None
