"""Transport schemas for roles."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_CODE = r"^[a-z][a-z0-9_]{1,49}$"


class RoleCreate(BaseModel):
    code: str = Field(..., pattern=_CODE)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    hierarchy_level: int = Field(1, ge=0, le=99, description="Below 100 (owner) and the level of the creator")
    permissions: list[str] = Field(
        default_factory=list,
        description="Catalogue codes (module.resource:action); unknown codes are refused",
    )


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    hierarchy_level: int | None = Field(None, ge=0, le=99)
    status: str | None = Field(None, pattern="^(active|inactive|deprecated)$")
    is_assignable: bool | None = None
    row_version: int = Field(..., ge=1)


class RolePermissionsReplace(BaseModel):
    """Replace a CUSTOM role's whole permission set (diff-applied, audited)."""

    permissions: list[str]
    row_version: int = Field(..., ge=1)


class RoleClone(BaseModel):
    code: str = Field(..., pattern=_CODE)
    name: str | None = Field(None, min_length=1, max_length=255)
    organization: str | None = Field(
        None, description="Organization uuid or code to clone into (default: the current organization)",
    )


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    #: Explicit codes; for a computed role (owner/admin) the catalogue expanded for you.
    permissions: list[str] = []
    grant_mode: str = "explicit"
    hierarchy_level: int = 1
    is_assignable: bool = True
    is_system: bool
    status: str
    tenant_id: int
    organization_id: int
    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
