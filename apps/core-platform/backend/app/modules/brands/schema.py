"""Transport schemas for the ``core.brands`` tables.

Slim vs Fat (master prompt, ``<slim_fat_query_doctrine>``): lists return
``BrandSlimOut`` backed by ``load_only``; the detail read returns ``BrandOut``
with its manufacturer links.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import BaseModel, ConfigDict, Field

from app.modules.brands.enums import BrandKind, BrandManufacturerKind, BrandStatus


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BrandSlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    name: str
    slug: str | None = None
    code: str | None = None
    status: str
    kind: str | None = None
    country_code: str | None = None
    parent_id: int | None = None
    is_verified: bool = False


class BrandManufacturerLinkOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    brand_id: int
    manufacturer_id: int
    kind: str | None = None
    is_default: bool | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    created_at: dt.datetime


class BrandOut(BrandSlimOut):
    organization_id: int
    owner_type: str | None = None
    owner_id: int | None = None
    description: str | None = None
    website_url: str | None = None
    logo_storage_key: str | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    manufacturer_links: list[BrandManufacturerLinkOut] = []


class BrandCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    slug: str | None = Field(None, max_length=200)
    code: str | None = Field(None, max_length=64)
    kind: BrandKind | None = None
    parent_id: int | None = Field(None, ge=1)
    country_code: str | None = Field(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    description: str | None = None
    website_url: str | None = Field(None, max_length=2048)
    logo_storage_key: str | None = Field(None, max_length=512)


class BrandUpdate(BaseModel):
    """PATCH — only the fields you send change. ``row_version`` is the version
    you loaded; a mismatch is a 409 rather than a silent overwrite."""

    name: str | None = Field(None, min_length=1, max_length=500)
    slug: str | None = Field(None, max_length=200)
    code: str | None = Field(None, max_length=64)
    kind: BrandKind | None = None
    parent_id: int | None = Field(None, ge=1)
    country_code: str | None = Field(None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    description: str | None = None
    website_url: str | None = Field(None, max_length=2048)
    logo_storage_key: str | None = Field(None, max_length=512)
    status: BrandStatus | None = None

    row_version: int = Field(..., ge=1)


class BrandManufacturerLinkCreate(BaseModel):
    manufacturer_id: int = Field(..., ge=1)
    kind: BrandManufacturerKind | None = None
    is_default: bool = False
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


__all__ = [
    "BrandCreate",
    "BrandManufacturerLinkCreate",
    "BrandManufacturerLinkOut",
    "BrandOut",
    "BrandSlimOut",
    "BrandUpdate",
]
