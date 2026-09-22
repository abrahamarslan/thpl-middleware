"""Manufacturer master business logic.

| Rule | Enforced by |
|---|---|
| a manufacturer always belongs to one organization of the tenant | ``OrgEntityMixin`` + ``require_organization`` |
| one live manufacturer per (tenant, organization, normalized name / code / slug) | partial unique indexes + ``_unique_slug`` |
| an identifier belongs to the same organization as its manufacturer | composite FK (DB) |
| statutory identifier formats (GSTIN/PAN/CIN/FSSAI) | CHECK constraint (DB) + ``_validate_format`` (early 422) |
| one live identifier per (manufacturer, kind, value) | partial unique index |
| concurrent edits don't overwrite each other | ``row_version`` |
"""

from __future__ import annotations

import re
import uuid as uuid_lib
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.entities.enums import MasterOwnerType
from app.modules.entities.scope import CoreRuleError, require_organization
from app.modules.manufacturers import crud
from app.modules.manufacturers.enums import ManufacturerIdentifierKind
from app.modules.manufacturers.model import Manufacturer, ManufacturerIdentifier
from app.modules.manufacturers.schema import (
    ManufacturerCreate,
    ManufacturerIdentifierCreate,
    ManufacturerUpdate,
)

logger = structlog.get_logger("app.manufacturers")

_ENUM_FIELDS = ("status",)

#: Statutory formats, mirrored by ``ck_manufacturer_identifiers_format``.
_IDENTIFIER_FORMATS = {
    ManufacturerIdentifierKind.GSTIN: re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
    ManufacturerIdentifierKind.PAN: re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$"),
    ManufacturerIdentifierKind.CIN: re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$"),
    ManufacturerIdentifierKind.FSSAI: re.compile(r"^[0-9]{14}$"),
}


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


def _normalize_value(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _validate_format(kind: str | None, value: str) -> None:
    pattern = _IDENTIFIER_FORMATS.get(ManufacturerIdentifierKind(kind)) if kind else None
    if pattern is not None and not pattern.match(value):
        raise CoreRuleError(
            f"'{value}' is not a valid {kind}",
            data={"kind": kind, "value": value},
        )


async def _unique_slug(
    db: AsyncSession, organization_id: int, name: str, *, exclude_id: int | None = None,
) -> str:
    base = _slugify(name)[:180] or "manufacturer"
    candidate, n = base, 2
    while True:
        existing = await crud.find_by_slug(db, organization_id, candidate)
        if existing is None or existing.id == exclude_id:
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def list_manufacturers(
    db: AsyncSession, *, q: str | None = None, status: str | None = None,
    page: int = 1, page_size: int = 100,
) -> list[Manufacturer]:
    return await crud.list_manufacturers(db, q=q, status=status, page=page, page_size=page_size)


async def get_manufacturer(db: AsyncSession, ref: str) -> Manufacturer:
    manufacturer = await crud.get_manufacturer(db, ref)
    if manufacturer is None:
        raise NotFoundError(f"Manufacturer '{ref}' not found")
    return manufacturer


async def create_manufacturer(
    db: AsyncSession, body: ManufacturerCreate, *, actor_id: int | None = None,
) -> Manufacturer:
    organization_id = await require_organization(db)
    values = _stringify(body.model_dump(exclude_none=True))
    values["name"] = body.name.strip()
    if values.get("country_code"):
        values["country_code"] = values["country_code"].upper()
    if await crud.find_by_name(db, organization_id, _normalize_name(body.name)) is not None:
        raise ConflictError(f"A manufacturer named '{body.name}' already exists for this organization")
    if body.code and await crud.find_by_code(db, organization_id, body.code) is not None:
        raise ConflictError(f"Manufacturer code '{body.code}' already exists for this organization")
    values["slug"] = body.slug or await _unique_slug(db, organization_id, body.name)

    manufacturer = Manufacturer(
        **values,
        organization_id=organization_id,
        owner_type=MasterOwnerType.ORGANIZATION.value,
        owner_id=organization_id,
    )
    db.add(manufacturer)
    await db.flush()
    await record_activity(
        db, action="manufacturer_created", actor_id=actor_id, subject_type="Manufacturer",
        subject_id=str(manufacturer.uuid),
        changes={"after": {"name": manufacturer.name, "code": manufacturer.code, "slug": manufacturer.slug}},
    )
    logger.info("manufacturer.created", manufacturer_id=manufacturer.id, organization_id=organization_id)
    return await crud.get_manufacturer(db, str(manufacturer.uuid)) or manufacturer


async def update_manufacturer(
    db: AsyncSession, ref: str, body: ManufacturerUpdate, *, actor_id: int | None = None,
) -> Manufacturer:
    manufacturer = await get_manufacturer(db, ref)
    _check_version(manufacturer, body.row_version, f"Manufacturer '{manufacturer.name}'")
    changes = _stringify(body.model_dump(exclude_unset=True, exclude={"row_version"}))

    if changes.get("name"):
        changes["name"] = changes["name"].strip()
        existing = await crud.find_by_name(db, manufacturer.organization_id, _normalize_name(changes["name"]))
        if existing is not None and existing.id != manufacturer.id:
            raise ConflictError(f"A manufacturer named '{changes['name']}' already exists for this organization")
    if changes.get("country_code"):
        changes["country_code"] = changes["country_code"].upper()
    if changes.get("code"):
        existing = await crud.find_by_code(db, manufacturer.organization_id, changes["code"])
        if existing is not None and existing.id != manufacturer.id:
            raise ConflictError(f"Manufacturer code '{changes['code']}' already exists for this organization")

    if "name" in changes and "slug" not in changes:
        changes["slug"] = await _unique_slug(db, manufacturer.organization_id, changes["name"],
                                             exclude_id=manufacturer.id)
    elif changes.get("slug"):
        other = await crud.find_by_slug(db, manufacturer.organization_id, changes["slug"])
        if other is not None and other.id != manufacturer.id:
            raise ConflictError(f"Manufacturer slug '{changes['slug']}' already exists for this organization")

    for field, value in changes.items():
        setattr(manufacturer, field, value)
    await db.flush()
    await record_activity(
        db, action="manufacturer_updated", actor_id=actor_id, subject_type="Manufacturer",
        subject_id=str(manufacturer.uuid),
        changes={"after": {k: str(v) for k, v in changes.items()}},
    )
    return await crud.get_manufacturer(db, str(manufacturer.uuid)) or manufacturer


async def delete_manufacturer(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    manufacturer = await get_manufacturer(db, ref)
    for identifier in await crud.list_identifiers(db, manufacturer.id):
        identifier.soft_delete(reason=f"manufacturer {manufacturer.uuid} deleted: {reason}", by=actor_id)
    manufacturer.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="manufacturer_deleted", actor_id=actor_id, subject_type="Manufacturer",
        subject_id=str(manufacturer.uuid), context={"reason": reason},
    )


# ── identifiers ──────────────────────────────────────────────────────────────

async def list_identifiers(db: AsyncSession, ref: str) -> list[ManufacturerIdentifier]:
    manufacturer = await get_manufacturer(db, ref)
    return await crud.list_identifiers(db, manufacturer.id)


async def add_identifier(
    db: AsyncSession, ref: str, body: ManufacturerIdentifierCreate, *, actor_id: int | None = None,
) -> ManufacturerIdentifier:
    manufacturer = await get_manufacturer(db, ref)
    kind = body.kind.value if body.kind else None
    normalized = _normalize_value(body.value)
    _validate_format(kind, normalized)

    existing = await crud.current_identifier(db, manufacturer.id, kind, normalized)
    if existing is not None:
        raise ConflictError(f"This manufacturer already has the same {kind or 'identifier'} value")

    identifier = await crud.create_identifier(db, {
        "manufacturer_id": manufacturer.id,
        "kind": kind,
        "value": body.value.strip(),
        "issuing_authority": body.issuing_authority,
        "issued_on": body.issued_on,
        "expires_on": body.expires_on,
    })
    await record_activity(
        db, action="manufacturer_identifier_added", actor_id=actor_id, subject_type="Manufacturer",
        subject_id=str(manufacturer.uuid), changes={"after": {"kind": kind}},
    )
    logger.info("manufacturer.identifier.added", manufacturer_id=manufacturer.id, kind=kind)
    return identifier


async def remove_identifier(
    db: AsyncSession, ref: str, identifier_ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    manufacturer = await get_manufacturer(db, ref)
    try:
        identifier_uuid = uuid_lib.UUID(identifier_ref)
    except ValueError:
        raise NotFoundError(f"Identifier '{identifier_ref}' not found") from None
    identifier = await crud.get_identifier(db, manufacturer.id, identifier_uuid)
    if identifier is None:
        raise NotFoundError(f"Identifier '{identifier_ref}' not found")
    identifier.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="manufacturer_identifier_removed", actor_id=actor_id, subject_type="Manufacturer",
        subject_id=str(manufacturer.uuid), context={"reason": reason},
    )
