"""Transport schemas for locations (read-only mirror)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None = None
    location_name: str | None = None
    type: str | None = None
    zoho_status: str | None = None
    status: str | None = None
    is_primary: bool | None = None
    email: str | None = None
    phone: str | None = None
    parent_location_id: str | None = None
    tax_settings_id: str | None = None
    associated_users: list[dict] | None = None
    address_attention: str | None = None
    address_street1: str | None = None
    address_street2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_state_code: str | None = None
    address_country: str | None = None
    synced_at: datetime | None = None
