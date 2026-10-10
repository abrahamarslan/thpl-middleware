"""Catalogue masters — business rules.

| Rule | Enforced by |
|---|---|
| every row belongs to one organization of the tenant | ``OrgEntityMixin`` (DB) + ``require_organization`` |
| codes are unique per organization among live rows (units case-insensitively) | partial unique indexes + checks here (clean 409) |
| codes are canonical: packaging/channel/group codes UPPER, attribute codes lower | normalized here; CHECK in the DB |
| a unit's class never changes (a "box" cannot become "500 g") | not in ``UnitUpdate`` |
| ``si_factor`` only on physical units | here (422) + ``ck_units_si_factor`` |
| a unit's UQC is an active GST code | here (422) + FK |
| a packaging weight unit is a mass unit, a dimension unit a length unit, of the same organization | here (422) + composite FK |
| an item group is never its own ancestor; a group with children is not deleted | here (walk) + ``ck_item_groups_no_self_parent`` |
| seeded (system) units and units in use are never deleted — deactivate instead | here (409 ``catalogue_in_use``) |
| fields Zoho feeds are read-only on a Zoho-linked unit | ``_guard_zoho_owned`` (409 ``zoho_owned_field``) |
| concurrent edits never overwrite each other | ``row_version`` (409) |

Deletes are soft (``deleted_at``), never ``session.delete()``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.catalogue.crud import masters as crud
from app.modules.catalogue.enums import UnitClass
from app.modules.catalogue.errors import (
    CatalogueInUseError,
    CatalogueRuleError,
    ZohoOwnedFieldError,
    require_organization,
)
from app.modules.catalogue.model import (
    Attribute,
    AttributeOption,
    ItemGroup,
    PackagingType,
    SalesChannel,
    Unit,
)
from app.modules.catalogue.schema.masters import (
    AttributeCreate,
    AttributeOptionCreate,
    AttributeOptionUpdate,
    AttributeUpdate,
    ItemGroupCreate,
    ItemGroupNode,
    ItemGroupSlimOut,
    ItemGroupUpdate,
    PackagingTypeCreate,
    PackagingTypeUpdate,
    SalesChannelCreate,
    SalesChannelUpdate,
    UnitCreate,
    UnitUpdate,
)

logger = structlog.get_logger("app.catalogue.masters")

#: Columns the (future) Zoho ``units`` adapter feeds — read-only on a linked unit until push exists.
ZOHO_OWNED_UNIT_FIELDS: frozenset[str] = frozenset({"code", "name", "uqc_code", "decimal_places", "status"})

_LABEL = {
    Unit: "Unit", PackagingType: "Packaging type", SalesChannel: "Sales channel",
    ItemGroup: "Item group", Attribute: "Attribute",
}


# ── shared helpers ───────────────────────────────────────────────────────────

def _plain(values: dict) -> dict:
    """Enum members → their values (columns store plain strings)."""
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _check_version(row: Any, seen: int) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{_LABEL.get(type(row), 'Row')} changed since you loaded it (version {seen} → {row.row_version}); "
            "reload and retry",
            data={"current_row_version": row.row_version},
        )


async def _get(db: AsyncSession, model: type, ref: str) -> Any:
    organization_id = await require_organization(db)
    row = await crud.get_by_ref(db, model, ref, organization_id=organization_id)
    if row is None:
        raise NotFoundError(f"{_LABEL[model]} '{ref}' not found")
    return row


async def _unique_code(
    db: AsyncSession, model: type, organization_id: int, *, column: str, value: str, exclude_id: int | None = None,
) -> None:
    existing = await crud.find_by(db, model, organization_id=organization_id, **{column: value})
    if existing is not None and existing.id != exclude_id:
        raise ConflictError(f"{_LABEL[model]} code '{value}' already exists in this organization",
                            data={"code": value})


async def _audit(db: AsyncSession, action: str, row: Any, actor_id: int | None, **payload: Any) -> None:
    await record_activity(db, action=action, actor_id=actor_id, subject_type=type(row).__name__,
                          subject_id=str(row.uuid), **payload)


async def _soft_delete(db: AsyncSession, row: Any, *, reason: str, actor_id: int | None, action: str) -> None:
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await _audit(db, action, row, actor_id, context={"reason": reason})


async def _apply(db: AsyncSession, row: Any, changes: dict, *, actor_id: int | None, action: str) -> Any:
    for field, value in changes.items():
        setattr(row, field, value)
    await db.flush()
    await _audit(db, action, row, actor_id, changes={"after": {k: str(v) for k, v in changes.items()}})
    return row


async def _unit_of_class(
    db: AsyncSession, organization_id: int, unit_id: int, allowed: Iterable[UnitClass], role: str,
) -> Unit:
    unit = await crud.get_by_id(db, Unit, unit_id, organization_id=organization_id)
    if unit is None:
        raise CatalogueRuleError(f"{role}: unit {unit_id} does not exist in this organization",
                                 data={"field": role, "unit_id": unit_id})
    allowed = tuple(allowed)
    if unit.unit_class not in {c.value for c in allowed}:
        raise CatalogueRuleError(
            f"{role}: unit '{unit.code}' is a {unit.unit_class} unit; expected {' or '.join(c.value for c in allowed)}",
            data={"field": role, "unit_id": unit_id, "unit_class": unit.unit_class},
        )
    return unit


# ── UQC ──────────────────────────────────────────────────────────────────────

async def list_uqc_codes(db: AsyncSession, *, include_inactive: bool = False):
    return await crud.list_uqc_codes(db, active_only=not include_inactive)


async def _valid_uqc(db: AsyncSession, code: str | None) -> str | None:
    if code is None:
        return None
    code = code.strip().upper()
    uqc = await crud.get_uqc(db, code)
    if uqc is None or not uqc.is_active:
        raise CatalogueRuleError(f"'{code}' is not an active GST UQC", data={"field": "uqc_code", "uqc_code": code})
    return code


# ── units ────────────────────────────────────────────────────────────────────

def _check_si_factor(unit_class: str, si_factor: Any) -> None:
    if si_factor is not None and not UnitClass(unit_class).is_physical:
        raise CatalogueRuleError(
            f"A {unit_class} unit has no physical size: si_factor is only for mass / volume / length / area / time "
            "units (a box's size is a property of each item's packaging hierarchy)",
            data={"field": "si_factor", "unit_class": unit_class},
        )


async def list_units(db: AsyncSession, *, q=None, unit_class=None, status=None, limit=100, offset=0):
    organization_id = await require_organization(db)
    return await crud.list_page(db, Unit, organization_id=organization_id, q=q,
                                filters={"unit_class": unit_class, "status": status}, limit=limit, offset=offset)


async def get_unit(db: AsyncSession, ref: str) -> Unit:
    return await _get(db, Unit, ref)


async def create_unit(db: AsyncSession, body: UnitCreate, *, actor_id: int | None = None) -> Unit:
    organization_id = await require_organization(db)
    values = _plain(body.model_dump(exclude_none=True))
    values["code"] = body.code.strip()
    values["name"] = body.name.strip()
    _check_si_factor(values["unit_class"], body.si_factor)
    values["uqc_code"] = await _valid_uqc(db, body.uqc_code)
    await _unique_code(db, Unit, organization_id, column="code_normalized", value=values["code"].lower())
    unit = Unit(**values, organization_id=organization_id)
    db.add(unit)
    await db.flush()
    await _audit(db, "catalogue_unit_created", unit, actor_id, changes={"after": {"code": unit.code}})
    logger.info("catalogue.unit.created", unit_id=unit.id, organization_id=organization_id)
    return unit


async def update_unit(db: AsyncSession, ref: str, body: UnitUpdate, *, actor_id: int | None = None) -> Unit:
    unit = await get_unit(db, ref)
    _check_version(unit, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if unit.zoho_id is not None:
        blocked = sorted(set(changes) & ZOHO_OWNED_UNIT_FIELDS)
        if blocked:
            raise ZohoOwnedFieldError(
                f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for unit "
                f"'{unit.code}' (zoho_id {unit.zoho_id}); change it in Zoho — the next sync brings it here",
                data={"zoho_owned": blocked},
            )
    if "code" in changes:
        changes["code"] = changes["code"].strip()
        await _unique_code(db, Unit, unit.organization_id, column="code_normalized",
                           value=changes["code"].lower(), exclude_id=unit.id)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    if "uqc_code" in changes:
        changes["uqc_code"] = await _valid_uqc(db, changes["uqc_code"])
    if "si_factor" in changes:
        _check_si_factor(unit.unit_class, changes["si_factor"])
    return await _apply(db, unit, changes, actor_id=actor_id, action="catalogue_unit_updated")


async def delete_unit(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    unit = await get_unit(db, ref)
    if unit.is_system:
        raise CatalogueInUseError(f"'{unit.code}' is a standard unit; deactivate it instead of deleting it",
                                  data={"unit": unit.code})
    if await crud.unit_in_use(db, unit.id):
        raise CatalogueInUseError(f"Unit '{unit.code}' is in use; deactivate it instead", data={"unit": unit.code})
    await _soft_delete(db, unit, reason=reason, actor_id=actor_id, action="catalogue_unit_deleted")


# ── packaging types ──────────────────────────────────────────────────────────

async def _check_packaging_units(db: AsyncSession, organization_id: int, values: dict) -> None:
    if values.get("weight_unit_id") is not None:
        await _unit_of_class(db, organization_id, values["weight_unit_id"], (UnitClass.MASS,), "weight_unit_id")
    if values.get("dimension_unit_id") is not None:
        await _unit_of_class(db, organization_id, values["dimension_unit_id"], (UnitClass.LENGTH,),
                             "dimension_unit_id")


def _check_window(valid_from: Any, valid_to: Any) -> None:
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise CatalogueRuleError("valid_to must be after valid_from", data={"field": "valid_to"})


async def list_packaging_types(db: AsyncSession, *, q=None, status=None, limit=100, offset=0):
    organization_id = await require_organization(db)
    return await crud.list_page(db, PackagingType, organization_id=organization_id, q=q,
                                filters={"status": status}, limit=limit, offset=offset)


async def get_packaging_type(db: AsyncSession, ref: str) -> PackagingType:
    return await _get(db, PackagingType, ref)


async def create_packaging_type(db: AsyncSession, body: PackagingTypeCreate, *, actor_id: int | None = None):
    organization_id = await require_organization(db)
    values = _plain(body.model_dump(exclude_none=True))
    values["code"] = body.code.strip().upper()
    values["name"] = body.name.strip()
    _check_window(body.valid_from, body.valid_to)
    await _check_packaging_units(db, organization_id, values)
    await _unique_code(db, PackagingType, organization_id, column="code", value=values["code"])
    row = PackagingType(**values, organization_id=organization_id)
    db.add(row)
    await db.flush()
    await _audit(db, "catalogue_packaging_type_created", row, actor_id, changes={"after": {"code": row.code}})
    return row


async def update_packaging_type(db: AsyncSession, ref: str, body: PackagingTypeUpdate, *, actor_id: int | None = None):
    row = await get_packaging_type(db, ref)
    _check_version(row, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if "code" in changes:
        changes["code"] = changes["code"].strip().upper()
        await _unique_code(db, PackagingType, row.organization_id, column="code", value=changes["code"],
                           exclude_id=row.id)
    _check_window(changes.get("valid_from", row.valid_from), changes.get("valid_to", row.valid_to))
    await _check_packaging_units(db, row.organization_id, changes)
    return await _apply(db, row, changes, actor_id=actor_id, action="catalogue_packaging_type_updated")


async def delete_packaging_type(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    row = await get_packaging_type(db, ref)
    await _soft_delete(db, row, reason=reason, actor_id=actor_id, action="catalogue_packaging_type_deleted")


# ── sales channels ───────────────────────────────────────────────────────────

async def _unique_zoho_code(db: AsyncSession, organization_id: int, zoho_code: str, exclude_id: int | None = None):
    existing = await crud.find_by(db, SalesChannel, organization_id=organization_id, zoho_code=zoho_code)
    if existing is not None and existing.id != exclude_id:
        raise ConflictError(f"Zoho sales channel '{zoho_code}' is already mapped to '{existing.code}'",
                            data={"zoho_code": zoho_code})


async def list_sales_channels(db: AsyncSession, *, q=None, status=None, channel_kind=None, limit=100, offset=0):
    organization_id = await require_organization(db)
    return await crud.list_page(db, SalesChannel, organization_id=organization_id, q=q,
                                filters={"status": status, "channel_kind": channel_kind}, limit=limit, offset=offset)


async def get_sales_channel(db: AsyncSession, ref: str) -> SalesChannel:
    return await _get(db, SalesChannel, ref)


async def create_sales_channel(db: AsyncSession, body: SalesChannelCreate, *, actor_id: int | None = None):
    organization_id = await require_organization(db)
    values = _plain(body.model_dump(exclude_none=True))
    values["code"] = body.code.strip().upper()
    values["name"] = body.name.strip()
    await _unique_code(db, SalesChannel, organization_id, column="code", value=values["code"])
    if body.zoho_code:
        values["zoho_code"] = body.zoho_code.strip()
        await _unique_zoho_code(db, organization_id, values["zoho_code"])
    row = SalesChannel(**values, organization_id=organization_id)
    db.add(row)
    await db.flush()
    await _audit(db, "catalogue_sales_channel_created", row, actor_id, changes={"after": {"code": row.code}})
    return row


async def update_sales_channel(db: AsyncSession, ref: str, body: SalesChannelUpdate, *, actor_id: int | None = None):
    row = await get_sales_channel(db, ref)
    _check_version(row, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if "code" in changes:
        changes["code"] = changes["code"].strip().upper()
        await _unique_code(db, SalesChannel, row.organization_id, column="code", value=changes["code"],
                           exclude_id=row.id)
    if changes.get("zoho_code"):
        changes["zoho_code"] = changes["zoho_code"].strip()
        await _unique_zoho_code(db, row.organization_id, changes["zoho_code"], exclude_id=row.id)
    return await _apply(db, row, changes, actor_id=actor_id, action="catalogue_sales_channel_updated")


async def delete_sales_channel(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    row = await get_sales_channel(db, ref)
    await _soft_delete(db, row, reason=reason, actor_id=actor_id, action="catalogue_sales_channel_deleted")


# ── item groups ──────────────────────────────────────────────────────────────

async def _validate_parent(db: AsyncSession, group: ItemGroup | None, parent_id: int, organization_id: int) -> None:
    if group is not None and parent_id == group.id:
        raise CatalogueRuleError("An item group cannot be its own parent", data={"field": "parent_id"})
    cursor = await crud.get_by_id(db, ItemGroup, parent_id, organization_id=organization_id)
    if cursor is None:
        raise CatalogueRuleError(f"Parent item group {parent_id} does not exist in this organization",
                                 data={"field": "parent_id"})
    seen: set[int] = set()
    while cursor is not None:
        if group is not None and cursor.id == group.id:
            raise CatalogueRuleError(f"Moving item group '{group.code}' under {parent_id} would create a cycle",
                                     data={"field": "parent_id"})
        if cursor.parent_id is None or cursor.parent_id in seen:
            return
        seen.add(cursor.parent_id)
        cursor = await crud.get_by_id(db, ItemGroup, cursor.parent_id, organization_id=organization_id)


async def list_item_groups(db: AsyncSession, *, q=None, status=None, parent_id=None, limit=100, offset=0):
    organization_id = await require_organization(db)
    return await crud.list_page(db, ItemGroup, organization_id=organization_id, q=q,
                                filters={"status": status, "parent_id": parent_id}, limit=limit, offset=offset)


async def item_group_tree(db: AsyncSession) -> list[ItemGroupNode]:
    """The whole merchandising tree, ordered by display order then name (one query)."""
    organization_id = await require_organization(db)
    rows = await crud.list_all(db, ItemGroup, organization_id=organization_id)
    nodes = {r.id: ItemGroupNode(**ItemGroupSlimOut.model_validate(r).model_dump()) for r in rows}
    roots: list[ItemGroupNode] = []
    for row in rows:
        node = nodes[row.id]
        parent = nodes.get(row.parent_id) if row.parent_id is not None else None
        (parent.children if parent is not None else roots).append(node)
    return roots


async def get_item_group(db: AsyncSession, ref: str) -> ItemGroup:
    return await _get(db, ItemGroup, ref)


async def create_item_group(db: AsyncSession, body: ItemGroupCreate, *, actor_id: int | None = None):
    organization_id = await require_organization(db)
    values = _plain(body.model_dump(exclude_none=True))
    values["code"] = body.code.strip().upper()
    values["name"] = body.name.strip()
    await _unique_code(db, ItemGroup, organization_id, column="code", value=values["code"])
    if body.parent_id is not None:
        await _validate_parent(db, None, body.parent_id, organization_id)
    row = ItemGroup(**values, organization_id=organization_id)
    db.add(row)
    await db.flush()
    await _audit(db, "catalogue_item_group_created", row, actor_id, changes={"after": {"code": row.code}})
    return row


async def update_item_group(db: AsyncSession, ref: str, body: ItemGroupUpdate, *, actor_id: int | None = None):
    row = await get_item_group(db, ref)
    _check_version(row, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if "code" in changes:
        changes["code"] = changes["code"].strip().upper()
        await _unique_code(db, ItemGroup, row.organization_id, column="code", value=changes["code"],
                           exclude_id=row.id)
    if changes.get("parent_id") is not None:
        await _validate_parent(db, row, changes["parent_id"], row.organization_id)
    return await _apply(db, row, changes, actor_id=actor_id, action="catalogue_item_group_updated")


async def delete_item_group(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    row = await get_item_group(db, ref)
    if await crud.group_children_exist(db, row.id):
        raise CatalogueInUseError(f"Item group '{row.code}' has sub-groups; move or delete them first",
                                  data={"item_group": row.code})
    await _soft_delete(db, row, reason=reason, actor_id=actor_id, action="catalogue_item_group_deleted")


# ── attributes & options ─────────────────────────────────────────────────────

async def list_attributes(db: AsyncSession, *, q=None, status=None, limit=100, offset=0):
    organization_id = await require_organization(db)
    return await crud.list_page(db, Attribute, organization_id=organization_id, q=q,
                                filters={"status": status}, limit=limit, offset=offset)


async def get_attribute(db: AsyncSession, ref: str) -> Attribute:
    return await _get(db, Attribute, ref)


async def attribute_options(db: AsyncSession, attribute: Attribute) -> list[AttributeOption]:
    return await crud.list_options(db, attribute.id)


async def _add_option(db: AsyncSession, attribute: Attribute, body: AttributeOptionCreate) -> AttributeOption:
    value = body.value.strip()
    if await crud.find_option(db, attribute.id, value.lower()) is not None:
        raise ConflictError(f"'{value}' is already an option of '{attribute.code}'", data={"value": value})
    option = AttributeOption(
        attribute_id=attribute.id, organization_id=attribute.organization_id, value=value,
        numeric_value=body.numeric_value, swatch=body.swatch, position=body.position,
    )
    db.add(option)
    await db.flush()
    return option


async def create_attribute(db: AsyncSession, body: AttributeCreate, *, actor_id: int | None = None) -> Attribute:
    organization_id = await require_organization(db)
    values = _plain(body.model_dump(exclude_none=True, exclude={"options"}))
    values["code"] = body.code.strip().lower()
    values["name"] = body.name.strip()
    await _unique_code(db, Attribute, organization_id, column="code", value=values["code"])
    if body.unit_id is not None:
        await _unit_of_class(db, organization_id, body.unit_id, tuple(UnitClass), "unit_id")
    row = Attribute(**values, organization_id=organization_id)
    db.add(row)
    await db.flush()
    for option in body.options:
        await _add_option(db, row, option)
    await _audit(db, "catalogue_attribute_created", row, actor_id,
                 changes={"after": {"code": row.code, "options": [o.value for o in body.options]}})
    return row


async def update_attribute(db: AsyncSession, ref: str, body: AttributeUpdate, *, actor_id: int | None = None):
    row = await get_attribute(db, ref)
    _check_version(row, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if "code" in changes:
        changes["code"] = changes["code"].strip().lower()
        await _unique_code(db, Attribute, row.organization_id, column="code", value=changes["code"],
                           exclude_id=row.id)
    if changes.get("unit_id") is not None:
        await _unit_of_class(db, row.organization_id, changes["unit_id"], tuple(UnitClass), "unit_id")
    return await _apply(db, row, changes, actor_id=actor_id, action="catalogue_attribute_updated")


async def delete_attribute(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    row = await get_attribute(db, ref)
    for option in await crud.list_options(db, row.id):
        option.soft_delete(reason=f"attribute {row.uuid} deleted: {reason}", by=actor_id)
    await _soft_delete(db, row, reason=reason, actor_id=actor_id, action="catalogue_attribute_deleted")


async def add_option(db: AsyncSession, ref: str, body: AttributeOptionCreate, *, actor_id: int | None = None):
    attribute = await get_attribute(db, ref)
    option = await _add_option(db, attribute, body)
    await _audit(db, "catalogue_attribute_option_added", attribute, actor_id, changes={"after": {"value": option.value}})
    return option


async def _get_option(db: AsyncSession, attribute: Attribute, option_ref: str) -> AttributeOption:
    option = await crud.get_option(db, attribute.id, option_ref)
    if option is None:
        raise NotFoundError(f"Option '{option_ref}' of '{attribute.code}' not found")
    return option


async def update_option(db: AsyncSession, ref: str, option_ref: str, body: AttributeOptionUpdate,
                        *, actor_id: int | None = None) -> AttributeOption:
    attribute = await get_attribute(db, ref)
    option = await _get_option(db, attribute, option_ref)
    _check_version(option, body.row_version)
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    if "value" in changes:
        changes["value"] = changes["value"].strip()
        existing = await crud.find_option(db, attribute.id, changes["value"].lower())
        if existing is not None and existing.id != option.id:
            raise ConflictError(f"'{changes['value']}' is already an option of '{attribute.code}'")
    for field, value in changes.items():
        setattr(option, field, value)
    await db.flush()
    await _audit(db, "catalogue_attribute_option_updated", attribute, actor_id,
                 changes={"after": {k: str(v) for k, v in changes.items()}})
    return option


async def delete_option(db: AsyncSession, ref: str, option_ref: str, *, reason: str,
                        actor_id: int | None = None) -> None:
    attribute = await get_attribute(db, ref)
    option = await _get_option(db, attribute, option_ref)
    option.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await _audit(db, "catalogue_attribute_option_deleted", attribute, actor_id, context={"reason": reason})
