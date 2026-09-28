"""Transport schemas for RBAC."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.rbac.enums import ScopeType


class PermissionOut(BaseModel):
    code: str
    module: str
    resource: str
    action: str
    description: str | None = None
    owner_only: bool = False


class PermissionGroupOut(BaseModel):
    module: str
    permissions: list[PermissionOut]


class UserRoleCreate(BaseModel):
    """Grant a role to a user at a scope beyond their base role."""

    role: str = Field(..., description="Role id or code (the role's organization must contain the scope)")
    scope_type: ScopeType = ScopeType.ORGANIZATION
    organization: str | None = Field(
        None, description="Organization uuid, code or id — required for scope_type=organization",
    )
    department_id: int | None = Field(None, gt=0)
    team_id: int | None = Field(None, gt=0)
    include_descendants: bool = True
    valid_from: datetime | None = None
    valid_to: datetime | None = Field(None, description="Omit for 'until revoked'")
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _scope_matches_columns(self) -> UserRoleCreate:
        t = self.scope_type
        if t == ScopeType.TENANT and (self.organization or self.department_id or self.team_id):
            raise ValueError("a tenant-wide grant takes no organization, department or team")
        if t == ScopeType.ORGANIZATION and not self.organization:
            raise ValueError("scope_type 'organization' needs an organization")
        if t == ScopeType.DEPARTMENT and not self.department_id:
            raise ValueError("scope_type 'department' needs department_id")
        if t == ScopeType.TEAM and not self.team_id:
            raise ValueError("scope_type 'team' needs team_id")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class UserRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    id: int
    user_id: int
    role_id: int
    role_code: str | None = None
    scope_type: str
    organization_id: int | None = None
    department_id: int | None = None
    team_id: int | None = None
    include_descendants: bool
    valid_from: datetime
    valid_to: datetime | None = None
    status: str
    reason: str | None = None
    created_by_name: str | None = None
    created_at: datetime


class BaseRoleSet(BaseModel):
    role: str = Field(..., description="Role id or code — must be a role of the user's own organization")


class GrantOut(BaseModel):
    source: str
    scope: str
    role: str
    role_id: int
    organization_id: int | None = None
    include_descendants: bool = False
    permissions: list[str]


class MyPermissionsOut(BaseModel):
    platform_admin: bool
    grants: list[GrantOut]
    #: Every distinct permission held at ANY scope — for showing/hiding UI, never for authorizing.
    permissions: list[str]
