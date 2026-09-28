"""Transport schemas for tenants."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.tenants.enums import TenantStatus

_CODE = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$"


class TenantBase(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    timezone: str | None = Field(None, max_length=50)
    locale: str | None = Field(None, max_length=10)
    primary_contact_email: EmailStr | None = None
    domain: str | None = Field(None, max_length=255)
    custom_attributes: dict | None = None


class TenantCreate(TenantBase):
    tenant_code: str = Field(..., pattern=_CODE)
    name: str = Field(..., min_length=1, max_length=255)
    primary_contact_email: EmailStr
    status: TenantStatus = TenantStatus.TRIAL
    #: The tenant's first organization (a root legal entity) is ALWAYS created with it; these only name it
    #: (defaults: the tenant's name and code).
    root_organization_name: str | None = Field(None, max_length=255)
    root_organization_code: str | None = Field(None, pattern=_CODE)
    #: The initial administrator — an ``owner`` of that organization AND of the whole tenant (so they may do
    #: anything, including creating new organizations). Default email: ``primary_contact_email``.
    admin_email: EmailStr | None = None
    admin_name: str | None = Field(None, max_length=255, description="Default: 'Administrator'")
    admin_password: str | None = Field(
        None, max_length=128,
        description="Omit to have a strong temporary password generated and returned ONCE in the response",
    )


class TenantUpdate(TenantBase):
    """PATCH semantics: only provided fields change. ``row_version`` is the
    version the client saw (optimistic lock)."""

    row_version: int = Field(..., ge=1)


class TenantStatusChange(BaseModel):
    status: TenantStatus
    reason: str = Field(..., min_length=3, max_length=500)


class InitialAdminOut(BaseModel):
    """The administrator created with a tenant. ``temporary_password`` is present ONLY when one was generated,
    and only in the creation response — it is never retrievable again."""

    user_id: int
    email: str
    role: str
    organization_code: str
    tenant_wide: bool
    temporary_password: str | None = None


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: uuid.UUID
    tenant_code: str
    name: str
    status: str
    is_verified: bool
    timezone: str
    locale: str
    primary_contact_email: str
    domain: str | None = None
    primary_user_id: int | None = None
    custom_attributes: dict = {}
    row_version: int
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class TenantCreatedOut(TenantOut):
    """The creation response: the tenant plus the administrator that was created with it."""

    initial_admin: InitialAdminOut | None = None
