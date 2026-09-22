"""Brand master business logic.

| Rule | Enforced by |
|---|---|
| a brand always belongs to one organization of the tenant | ``OrgEntityMixin`` (DB) + ``require_organization`` |
| one live brand per (tenant, organization, normalized name / code / slug) | partial unique indexes + ``_unique_slug`` |
| a sub-brand shares its parent's organization | ``fk_brands_parent`` (DB) |
| a brand cannot be its own ancestor | ``core.guard_brand_parent()`` (DB) + service walk |
| a link can never span two organizations | composite FKs (DB) |
| no overlapping windows per (brand, manufacturer, kind) | ``core.check_brand_manufacturer_overlap()`` (DB) |
| concurrent edits don't overwrite each other | ``row_version`` |

The brand master is canonical — it carries no source id. External identity lives
on the sync crosswalk when a brand is eventually linked to an ERP.
"""

from __future__ import annotations

import re
import uuid as uuid_lib
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.brands import crud
from app.modules.brands.model import Brand, BrandManufacturer
from app.modules.brands.schema import (
    BrandCreate,
    BrandManufacturerLinkCreate,
    BrandUpdate,
)
from app.modules.entities.enums import MasterOwnerType
from app.modules.entities.scope import CoreRuleError, require_organization

logger = structlog.get_logger("app.brands")

#: Enum-valued columns that must be written as plain strings.
_ENUM_FIELDS = ("kind", "status")


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


def _stringify(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


async def _unique_slug(
    db: AsyncSession, organization_id: int, name: str, *, exclude_id: int | None = None,
) -> str:
    base = _slugify(name)[:180] or "brand"
    candidate, n = base, 2
    while True:
        existing = await crud.find_by_slug(db, organization_id, candidate)
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def _validate_parent(
    db: AsyncSession, *, brand: Brand | None, parent_id: int, organization_id: int,
) -> None:
    if brand is not None and parent_id == brand.id:
        raise CoreRuleError("A brand cannot be its own parent")
    parent = await crud.get_by_id(db, parent_id)
    if parent is None:
        raise NotFoundError(f"Parent brand {parent_id} not found")
    if parent.organization_id != organization_id:
        raise CoreRuleError("The parent brand belongs to a different organization")

    # Walk up from the proposed parent; if we reach this brand, the move is a cycle.
    seen: set[int] = set()
    cursor: Brand | None = parent
    while cursor is not None:
        if brand is not None and cursor.id == brand.id:
            raise CoreRuleError(f"Moving brand {brand.id} under {parent_id} would create a cycle")
        if cursor.parent_id is None or cursor.parent_id in seen:
            break
        seen.add(cursor.parent_id)
        cursor = await crud.get_by_id(db, cursor.parent_id)


async def list_brands(
    db: AsyncSession, *, q: str | None = None, status: str | None = None, kind: str | None = None,
    parent_id: int | None = None, page: int = 1, page_size: int = 100,
) -> list[Brand]:
    return await crud.list_brands(db, q=q, status=status, kind=kind, parent_id=parent_id,
                                  page=page, page_size=page_size)


async def get_brand(db: AsyncSession, ref: str) -> Brand:
    brand = await crud.get_brand(db, ref)
    if brand is None:
        raise NotFoundError(f"Brand '{ref}' not found")
    return brand


async def create_brand(db: AsyncSession, body: BrandCreate, *, actor_id: int | None = None) -> Brand:
    organization_id = await require_organization(db)
    values = _stringify(body.model_dump(exclude_none=True))
    values["name"] = body.name.strip()
    if values.get("country_code"):
        values["country_code"] = values["country_code"].upper()
    if await crud.find_by_name(db, organization_id, _normalize_name(body.name)) is not None:
        raise ConflictError(f"A brand named '{body.name}' already exists for this organization")
    if body.code and await crud.find_by_code(db, organization_id, body.code) is not None:
        raise ConflictError(f"Brand code '{body.code}' already exists for this organization")
    if body.parent_id:
        await _validate_parent(db, brand=None, parent_id=body.parent_id, organization_id=organization_id)
    values["slug"] = body.slug or await _unique_slug(db, organization_id, body.name)

    brand = Brand(
        **values,
        organization_id=organization_id,
        owner_type=MasterOwnerType.ORGANIZATION.value,
        owner_id=organization_id,
    )
    db.add(brand)
    await db.flush()
    await record_activity(
        db, action="brand_created", actor_id=actor_id, subject_type="Brand", subject_id=str(brand.uuid),
        changes={"after": {"name": brand.name, "code": brand.code, "slug": brand.slug}},
    )
    logger.info("brand.created", brand_id=brand.id, organization_id=organization_id)
    return await crud.get_brand(db, str(brand.uuid)) or brand


async def update_brand(
    db: AsyncSession, ref: str, body: BrandUpdate, *, actor_id: int | None = None,
) -> Brand:
    brand = await get_brand(db, ref)
    _check_version(brand, body.row_version, f"Brand '{brand.name}'")
    changes = _stringify(body.model_dump(exclude_unset=True, exclude={"row_version"}))

    if changes.get("name"):
        changes["name"] = changes["name"].strip()
        existing = await crud.find_by_name(db, brand.organization_id, _normalize_name(changes["name"]))
        if existing is not None and existing.id != brand.id:
            raise ConflictError(f"A brand named '{changes['name']}' already exists for this organization")
    if changes.get("country_code"):
        changes["country_code"] = changes["country_code"].upper()
    if "parent_id" in changes and changes["parent_id"] is not None:
        await _validate_parent(db, brand=brand, parent_id=changes["parent_id"],
                               organization_id=brand.organization_id)
    if changes.get("code") and await crud.find_by_code(db, brand.organization_id, changes["code"]) is not None:
        existing = await crud.find_by_code(db, brand.organization_id, changes["code"])
        if existing is not None and existing.id != brand.id:
            raise ConflictError(f"Brand code '{changes['code']}' already exists for this organization")

    # A rename regenerates the slug unless the caller pinned one explicitly.
    if "name" in changes and "slug" not in changes:
        changes["slug"] = await _unique_slug(db, brand.organization_id, changes["name"], exclude_id=brand.id)
    elif changes.get("slug"):
        other = await crud.find_by_slug(db, brand.organization_id, changes["slug"])
        if other is not None and other.id != brand.id:
            raise ConflictError(f"Brand slug '{changes['slug']}' already exists for this organization")

    for field, value in changes.items():
        setattr(brand, field, value)
    await db.flush()
    await record_activity(
        db, action="brand_updated", actor_id=actor_id, subject_type="Brand", subject_id=str(brand.uuid),
        changes={"after": {k: str(v) for k, v in changes.items()}},
    )
    return await crud.get_brand(db, str(brand.uuid)) or brand


async def delete_brand(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    """Soft-delete the brand and its live manufacturer links (never a hard
    DELETE — FKs and children stay intact)."""
    brand = await get_brand(db, ref)
    for link in await crud.list_links(db, brand.id):
        link.soft_delete(reason=f"brand {brand.uuid} deleted: {reason}", by=actor_id)
    brand.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="brand_deleted", actor_id=actor_id, subject_type="Brand", subject_id=str(brand.uuid),
        context={"reason": reason},
    )


# ── brand ↔ manufacturer ─────────────────────────────────────────────────────

async def list_links(db: AsyncSession, ref: str) -> list[BrandManufacturer]:
    brand = await get_brand(db, ref)
    return await crud.list_links(db, brand.id)


async def link_manufacturer(
    db: AsyncSession, ref: str, body: BrandManufacturerLinkCreate, *, actor_id: int | None = None,
) -> BrandManufacturer:
    from app.modules.manufacturers.model import Manufacturer

    brand = await get_brand(db, ref)
    manufacturer = await db.get(Manufacturer, body.manufacturer_id)
    if manufacturer is None:
        raise NotFoundError(f"Manufacturer {body.manufacturer_id} not found")
    if manufacturer.organization_id != brand.organization_id:
        raise CoreRuleError("The manufacturer belongs to a different organization than the brand")

    kind = body.kind.value if body.kind else None
    existing = await crud.current_link(db, brand.id, manufacturer.id, kind)
    if existing is not None:
        raise ConflictError(
            "This brand and manufacturer are already linked with the same role and no end date"
        )
    if body.is_default:
        await crud.clear_other_defaults(db, brand.id, kind)

    link = await crud.create_link(db, {
        "brand_id": brand.id,
        "manufacturer_id": manufacturer.id,
        "kind": kind,
        "is_default": body.is_default,
        "valid_from": body.valid_from,
        "valid_to": body.valid_to,
    })
    await record_activity(
        db, action="brand_manufacturer_linked", actor_id=actor_id, subject_type="Brand",
        subject_id=str(brand.uuid),
        changes={"after": {"manufacturer_id": manufacturer.id, "kind": kind}},
    )
    logger.info("brand.manufacturer.linked", brand_id=brand.id, manufacturer_id=manufacturer.id)
    return link


async def unlink_manufacturer(
    db: AsyncSession, ref: str, link_ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    brand = await get_brand(db, ref)
    try:
        link_uuid = uuid_lib.UUID(link_ref)
    except ValueError:
        raise NotFoundError(f"Link '{link_ref}' not found") from None
    link = await crud.get_link(db, brand.id, link_uuid)
    if link is None:
        raise NotFoundError(f"Link '{link_ref}' not found")
    link.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="brand_manufacturer_unlinked", actor_id=actor_id, subject_type="Brand",
        subject_id=str(brand.uuid), context={"reason": reason},
    )
