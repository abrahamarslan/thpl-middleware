"""Transport schemas for ``core`` taxonomies, categories and assignments.

Slim vs Fat (master prompt, ``<slim_fat_query_doctrine>``): lists return a
Slim DTO backed by ``load_only``; detail reads return the Fat DTO with its
tags/documents eager-loaded. Per locked L1, ``CategorySlimOut`` still carries
the full tile/display set — the slimming is on the columns the list view does
not render, not on the approved display fields.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.modules.categories.enums import CategoryStatus, TaxonomyStatus
from app.modules.tags.schema import TagOut
from app.modules.taxes.assignment_schema import TaxAssignmentItem, TaxAssignmentOut

_OUT = ConfigDict(from_attributes=True, populate_by_name=True)


class _Out(BaseModel):
    model_config = _OUT


# ── taxonomy ─────────────────────────────────────────────────────────────────

class TaxonomySlimOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    slug: str
    name: str
    status: str


class TaxonomyEntityTypeOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    taxonomy_id: int
    entity_type_code: str
    allows_multiple: bool | None = None


class TaxonomyOut(TaxonomySlimOut):
    organization_id: int
    description: str | None = None
    is_verified: bool = False
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    entity_types: list[TaxonomyEntityTypeOut] = []


class TaxonomyCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=200)
    name: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    status: TaxonomyStatus | None = None


class TaxonomyUpdate(BaseModel):
    slug: str | None = Field(None, min_length=1, max_length=200)
    name: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    status: TaxonomyStatus | None = None
    row_version: int = Field(..., ge=1)


class TaxonomyEntityTypeItem(BaseModel):
    entity_type_code: str = Field(..., min_length=1, max_length=64)
    allows_multiple: bool | None = None


class TaxonomyEntityTypesReplace(BaseModel):
    entity_types: list[TaxonomyEntityTypeItem] = Field(default_factory=list)


# ── category ─────────────────────────────────────────────────────────────────

class CategorySlimOut(_Out):
    """List DTO: the full tile/display set (L1), backed by ``load_only``."""

    id: int
    uuid: uuid_lib.UUID
    taxonomy_id: int
    name: str
    # identity / display
    taxonomy_slug: str | None = None
    parent_id: int | None = None
    is_root: bool = False
    can_have_children: bool = True
    depth: int = 0
    category: str | None = None
    code: str | None = None
    title: str | None = None
    sub_title: str | None = None
    slug: str | None = None
    short_description: str | None = None
    description: str | None = None
    type: str | None = None
    ondc_category_type: str | None = None
    # ordering / flags
    position: int = 0
    display_order: int = 0
    menu_order: int = 0
    show_in_menu: bool = True
    status: str
    is_verified: bool = False
    is_active: bool = True
    is_blocked: bool = False
    is_featured: bool = False
    is_promoted: bool = False
    is_sponsored: bool = False
    is_partnered: bool = False
    is_visible: bool = True
    visibility: str | None = None
    is_bookmarked: bool = False
    # media / display (L1)
    icon: str | None = None
    color: str | None = None
    icon_color: str | None = None
    icon_bg_color: str | None = None
    icon_bg_image: str | None = None
    icon_border_color: str | None = None
    preview_image: str | None = None
    thumbnail: str | None = None
    banner: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    banner_url: str | None = None
    # buckets (L1)
    settings: dict | None = None
    metadata: dict | None = Field(None, validation_alias=AliasChoices("metadata_", "metadata"))
    extra_attributes: dict | None = None
    record_notes: dict | None = None


class AttachedDocumentRef(_Out):
    id: int
    uuid: uuid_lib.UUID


class CategoryOut(CategorySlimOut):
    organization_id: int
    lft: int = 0
    rgt: int = 0
    path: str | None = None
    record_order: int | None = None
    record_previous: int | None = None
    record_next: int | None = None
    record_status: int = 0
    record_tags: dict | None = None
    noteable_type: str | None = None
    noteable_id: int | None = None
    document_id: int | None = None
    documents_snapshot: dict | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    meta_keywords: list[str] | None = None
    deactivation_date: dt.datetime | None = None
    deactivation_reason: str | None = None
    zoho_id: str | None = None
    row_version: int
    created_by_name: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    tags: list[TagOut] = []
    documents: list[AttachedDocumentRef] = []
    # The category's taxes (tax.tax_assignments, owner class 'category'): one tax per
    # inter/intra context. Zoho-fed rows say so in `source_system`.
    tax_preferences: list[TaxAssignmentOut] = Field(default=[], validation_alias="tax_assignments")


class CategoryCreate(BaseModel):
    taxonomy_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=500)
    parent_id: int | None = Field(None, ge=1)
    slug: str | None = Field(None, max_length=200)
    code: str | None = Field(None, max_length=64)
    category: str | None = None
    title: str | None = None
    sub_title: str | None = None
    short_description: str | None = None
    description: str | None = None
    type: str | None = None
    ondc_category_type: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    meta_keywords: list[str] | None = None
    can_have_children: bool = True
    position: int = Field(0, ge=0)
    display_order: int = Field(0, ge=0)
    menu_order: int = Field(0, ge=0)
    show_in_menu: bool = True
    is_active: bool = True
    is_visible: bool = True
    visibility: str | None = Field(None, max_length=20)
    icon: str | None = None
    color: str | None = None
    icon_color: str | None = None
    icon_bg_color: str | None = None
    icon_bg_image: str | None = None
    icon_border_color: str | None = None
    preview_image: str | None = None
    thumbnail: str | None = None
    banner: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    banner_url: str | None = None
    settings: dict | None = None
    metadata: dict | None = None
    extra_attributes: dict | None = None
    record_notes: dict | None = None
    record_tags: dict | None = None
    tax_preferences: list[TaxAssignmentItem] | None = Field(
        None, max_length=10, description="The category's taxes, one per inter/intra context")


class CategoryUpdate(BaseModel):
    """PATCH — only provided fields change. ``row_version`` is the loaded version."""

    name: str | None = Field(None, min_length=1, max_length=500)
    parent_id: int | None = Field(None, ge=1)
    slug: str | None = Field(None, max_length=200)
    code: str | None = Field(None, max_length=64)
    category: str | None = None
    title: str | None = None
    sub_title: str | None = None
    short_description: str | None = None
    description: str | None = None
    type: str | None = None
    ondc_category_type: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    meta_keywords: list[str] | None = None
    can_have_children: bool | None = None
    position: int | None = Field(None, ge=0)
    display_order: int | None = Field(None, ge=0)
    menu_order: int | None = Field(None, ge=0)
    show_in_menu: bool | None = None
    status: CategoryStatus | None = None
    is_active: bool | None = None
    is_blocked: bool | None = None
    is_featured: bool | None = None
    is_promoted: bool | None = None
    is_sponsored: bool | None = None
    is_partnered: bool | None = None
    is_visible: bool | None = None
    visibility: str | None = Field(None, max_length=20)
    is_bookmarked: bool | None = None
    icon: str | None = None
    color: str | None = None
    icon_color: str | None = None
    icon_bg_color: str | None = None
    icon_bg_image: str | None = None
    icon_border_color: str | None = None
    preview_image: str | None = None
    thumbnail: str | None = None
    banner: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    banner_url: str | None = None
    settings: dict | None = None
    metadata: dict | None = None
    extra_attributes: dict | None = None
    record_notes: dict | None = None
    record_tags: dict | None = None
    tax_preferences: list[TaxAssignmentItem] | None = Field(
        None, max_length=10, description="Replaces the category's local taxes; [] clears them")

    row_version: int = Field(..., ge=1)


class CategoryMove(BaseModel):
    parent_id: int | None = Field(None, ge=1, description="new parent id; empty makes it a root")
    row_version: int = Field(..., ge=1)


# ── categorizable ────────────────────────────────────────────────────────────

class CategorizableOut(_Out):
    id: int
    uuid: uuid_lib.UUID
    category_id: int
    taxonomy_id: int
    categorizable_type: str
    categorizable_id: int
    sort_order: int = 0
    is_primary: bool = False
    is_featured: bool = False
    valid_from: dt.datetime
    valid_to: dt.datetime | None = None
    metadata: dict | None = Field(None, validation_alias=AliasChoices("metadata_", "metadata"))
    created_at: dt.datetime


class CategorizableCreate(BaseModel):
    category_id: int = Field(..., ge=1)
    categorizable_type: str = Field(..., min_length=1, max_length=64)
    categorizable_id: int = Field(..., ge=1)
    sort_order: int = Field(0, ge=0)
    is_primary: bool = False
    is_featured: bool = False
    valid_from: dt.datetime | None = None
    valid_to: dt.datetime | None = None
    metadata: dict | None = None


class CategorizableItem(BaseModel):
    category_id: int = Field(..., ge=1)
    sort_order: int = Field(0, ge=0)
    is_primary: bool = False
    is_featured: bool = False
    valid_from: dt.datetime | None = None
    valid_to: dt.datetime | None = None
    metadata: dict | None = None


class CategorizableSyncRequest(BaseModel):
    """Replace the live assignment set of one thing within one taxonomy."""

    categorizable_type: str = Field(..., min_length=1, max_length=64)
    categorizable_id: int = Field(..., ge=1)
    taxonomy_id: int = Field(..., ge=1)
    items: list[CategorizableItem] = Field(default_factory=list)


__all__ = [
    "AttachedDocumentRef",
    "CategoryCreate",
    "CategoryMove",
    "CategoryOut",
    "CategorySlimOut",
    "CategoryUpdate",
    "CategorizableCreate",
    "CategorizableItem",
    "CategorizableOut",
    "CategorizableSyncRequest",
    "TaxonomyCreate",
    "TaxonomyEntityTypeItem",
    "TaxonomyEntityTypeOut",
    "TaxonomyEntityTypesReplace",
    "TaxonomyOut",
    "TaxonomySlimOut",
    "TaxonomyUpdate",
]
