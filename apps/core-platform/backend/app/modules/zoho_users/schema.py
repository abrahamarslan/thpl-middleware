"""Transport schemas for Zoho users (read-only mirror)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ZohoUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    zoho_id: str | None = None
    name: str | None = None
    email: str | None = None
    user_role: str | None = None
    role_id: str | None = None
    zoho_status: str | None = None
    status: str | None = None
    user_type: str | None = None
    is_current_user: bool | None = None
    synced_at: datetime | None = None
