"""Transport schemas for the teams module.

The performance/incentive columns (``has_targets``, ``achievement_ratio``, …) are OUTPUT-ONLY:
reserved display data until a performance engine exists (docs/rbac-module.md D6). No create or
update schema accepts them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.teams.enums import ApprovalStatus, MembershipStatus

_CODE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$"
_ORM = ConfigDict(from_attributes=True)


class _Scoped(BaseModel):
    model_config = _ORM

    id: int
    uuid: uuid.UUID
    tenant_id: int
    organization_id: int
    status: str
    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class _TreeOut(_Scoped):
    parent_id: int | None = None
    is_root: bool = True
    depth: int = 0
    path: str | None = None
    position: int = 0


class Move(BaseModel):
    """Re-parent a node (``parent: null`` makes it a root)."""

    parent: str | None = Field(None, description="Parent uuid, code or id; null = root")
    row_version: int = Field(..., ge=1)


# ── departments ─────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    department_code: str = Field(..., pattern=_CODE)
    department_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    parent: str | None = Field(None, description="Parent department uuid, code or id")
    head_of_department_user_id: int | None = Field(None, gt=0)
    cost_center_code: str | None = Field(None, max_length=50)
    position: int = Field(0, ge=0)
    status: str = Field("active", pattern="^(active|inactive|archived)$")


class DepartmentUpdate(BaseModel):
    department_code: str | None = Field(None, pattern=_CODE)
    department_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    head_of_department_user_id: int | None = Field(None, gt=0)
    cost_center_code: str | None = Field(None, max_length=50)
    position: int | None = Field(None, ge=0)
    status: str | None = Field(None, pattern="^(active|inactive|archived)$")
    row_version: int = Field(..., ge=1)


class DepartmentOut(_TreeOut):
    department_code: str
    department_name: str
    description: str | None = None
    head_of_department_user_id: int | None = None
    cost_center_code: str | None = None


# ── job titles ──────────────────────────────────────────────────────────────

class JobTitleCreate(BaseModel):
    job_code: str = Field(..., pattern=_CODE)
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    department: str | None = Field(None, description="Department uuid, code or id")
    band_level: int = Field(1, ge=0, le=99)
    is_management: bool = False
    status: str = Field("active", pattern="^(active|inactive|deprecated)$")


class JobTitleUpdate(BaseModel):
    job_code: str | None = Field(None, pattern=_CODE)
    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    department: str | None = Field(None, description="Department uuid, code or id; '' clears it")
    band_level: int | None = Field(None, ge=0, le=99)
    is_management: bool | None = None
    status: str | None = Field(None, pattern="^(active|inactive|deprecated)$")
    row_version: int = Field(..., ge=1)


class JobTitleOut(_Scoped):
    job_code: str
    title: str
    description: str | None = None
    department_id: int | None = None
    band_level: int = 1
    is_management: bool = False


# ── team types ──────────────────────────────────────────────────────────────

class TeamTypeCreate(BaseModel):
    type_code: str = Field(..., pattern=_CODE)
    type_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    icon_class: str | None = Field(None, max_length=100)
    parent: str | None = Field(None, description="Parent team type uuid, code or id")
    position: int = Field(0, ge=0)
    status: str = Field("active", pattern="^(active|inactive|deprecated)$")


class TeamTypeUpdate(BaseModel):
    type_code: str | None = Field(None, pattern=_CODE)
    type_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    icon_class: str | None = Field(None, max_length=100)
    position: int | None = Field(None, ge=0)
    status: str | None = Field(None, pattern="^(active|inactive|deprecated)$")
    row_version: int = Field(..., ge=1)


class TeamTypeOut(_TreeOut):
    type_code: str
    type_name: str
    description: str | None = None
    category: str | None = None
    icon_class: str | None = None


# ── team roles ──────────────────────────────────────────────────────────────

class TeamRoleCreate(BaseModel):
    role_code: str = Field(..., pattern=_CODE)
    role_name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    team_type: str | None = Field(None, description="Team type uuid, code or id; omit for a role usable in any type")
    hierarchy_level: int = Field(1, ge=0, le=99)
    is_assignable: bool = True
    is_default: bool = False
    rbac_role: str | None = Field(
        None, description="RBAC role (id or code) a member holds, scoped to the team, while the membership is in force",
    )
    position: int = Field(0, ge=0)
    color_code: str | None = Field(None, max_length=20)
    icon_class: str | None = Field(None, max_length=100)
    status: str = Field("active", pattern="^(active|inactive|deprecated)$")


class TeamRoleUpdate(BaseModel):
    role_code: str | None = Field(None, pattern=_CODE)
    role_name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    hierarchy_level: int | None = Field(None, ge=0, le=99)
    is_assignable: bool | None = None
    is_default: bool | None = None
    rbac_role: str | None = Field(None, description="RBAC role id or code; '' unmaps it")
    position: int | None = Field(None, ge=0)
    color_code: str | None = Field(None, max_length=20)
    icon_class: str | None = Field(None, max_length=100)
    status: str | None = Field(None, pattern="^(active|inactive|deprecated)$")
    row_version: int = Field(..., ge=1)


class TeamRoleOut(_Scoped):
    role_code: str
    role_name: str
    description: str | None = None
    team_type_id: int | None = None
    hierarchy_level: int = 1
    is_assignable: bool = True
    is_default: bool = False
    rbac_role_id: int | None = None
    position: int = 0
    color_code: str | None = None
    icon_class: str | None = None


# ── teams ───────────────────────────────────────────────────────────────────

class TeamCreate(BaseModel):
    team_code: str = Field(..., pattern=_CODE)
    team_name: str = Field(..., min_length=1, max_length=150)
    team_type: str = Field(..., description="Team type uuid, code or id")
    description: str | None = None
    parent: str | None = Field(None, description="Parent team uuid, code or id")
    team_lead_user_id: int | None = Field(None, gt=0)
    department: str | None = Field(None, description="Department uuid, code or id")
    email_address: str | None = Field(None, max_length=255)
    operational_goal: str | None = None
    color_code: str | None = Field(None, max_length=20)
    icon_class: str | None = Field(None, max_length=100)
    position: int = Field(0, ge=0)
    status: str = Field("active", pattern="^(active|inactive|archived|pending)$")


class TeamUpdate(BaseModel):
    team_code: str | None = Field(None, pattern=_CODE)
    team_name: str | None = Field(None, min_length=1, max_length=150)
    team_type: str | None = Field(None, description="Team type uuid, code or id")
    description: str | None = None
    team_lead_user_id: int | None = Field(None, gt=0)
    department: str | None = Field(None, description="Department uuid, code or id; '' clears it")
    email_address: str | None = Field(None, max_length=255)
    operational_goal: str | None = None
    color_code: str | None = Field(None, max_length=20)
    icon_class: str | None = Field(None, max_length=100)
    position: int | None = Field(None, ge=0)
    status: str | None = Field(None, pattern="^(active|inactive|archived|pending)$")
    row_version: int = Field(..., ge=1)


class TeamOut(_TreeOut):
    team_code: str
    team_name: str
    team_type_id: int
    description: str | None = None
    team_lead_user_id: int | None = None
    department_id: int | None = None
    email_address: str | None = None
    operational_goal: str | None = None
    color_code: str | None = None
    icon_class: str | None = None
    # Reserved display data — output only, no logic (docs/rbac-module.md D6).
    has_targets: bool = False
    has_incentives: bool = False
    achievement_ratio: Decimal | None = None
    performance_last_updated: date | None = None
    performance_last_calculated_at: datetime | None = None


# ── membership ──────────────────────────────────────────────────────────────

class MemberAdd(BaseModel):
    user_id: int = Field(..., gt=0)
    team_role: str | None = Field(None, description="Team role uuid, code or id; default: the type's default role")
    is_primary: bool = False
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _window(self) -> MemberAdd:
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        return self


class MemberBulkItem(MemberAdd):
    team: str = Field(..., description="Team uuid, code or id")


class MembersBulk(BaseModel):
    items: list[MemberBulkItem] = Field(..., min_length=1, max_length=200)


class MemberUpdate(BaseModel):
    team_role: str | None = Field(None, description="Team role uuid, code or id")
    is_primary: bool | None = None
    status: str | None = Field(None, pattern="^(active|inactive|on_leave|transferred)$")
    valid_until: datetime | None = None
    notes: str | None = None
    row_version: int = Field(..., ge=1)


class MemberDecision(BaseModel):
    notes: str | None = Field(None, max_length=500)


class MemberOut(BaseModel):
    model_config = _ORM

    id: int
    uuid: uuid.UUID
    tenant_id: int
    organization_id: int
    user_id: int
    team_id: int
    team_role_id: int | None = None
    status: MembershipStatus | str
    is_primary: bool = False
    notes: str | None = None
    valid_from: datetime
    valid_until: datetime | None = None
    approval_status: ApprovalStatus | str
    approved_at: datetime | None = None
    approved_by: int | None = None
    approval_notes: str | None = None
    row_version: int
    created_at: datetime
    # Reserved display data — output only.
    has_individual_targets: bool = False
    has_custom_incentives: bool = False
    individual_achievement_ratio: Decimal | None = None


class BulkResult(BaseModel):
    added: list[MemberOut]
    denied: list[int] = []
    errors: list[dict] = []


class TreeNode(BaseModel):
    id: int
    uuid: uuid.UUID
    code: str
    name: str
    depth: int
    status: str
    children: list[TreeNode] = []
