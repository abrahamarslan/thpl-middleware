"""Transport schemas for roles."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_CODE = r"^[a-z][a-z0-9_]{1,49}$"


class RoleCreate(BaseModel):
    code: str = Field(..., pattern=_CODE)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    permissions: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    permissions: list[str] | None = None
    status: str | None = Field(None, pattern="^(active|inactive)$")
    row_version: int = Field(..., ge=1)


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    permissions: list[str] = []
    is_system: bool
    status: str
    tenant_id: int
    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
