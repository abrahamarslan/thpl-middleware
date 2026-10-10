"""Items — business rules (items, packaging hierarchy, identifiers, children, products, lookup).

| Rule | Enforced by |
|---|---|
| every referenced row (brand, manufacturer, group, product, units, vendors, channels, components) is in the item's organization | here (422) + composite FKs |
| SKU unique per organization (case-insensitive); code unique | here (409) + partial unique indexes |
| a kit has no stock; expiry needs lots; lots need inventory tracking; ``serial`` is not available yet | here (422) + CHECKs |
| weight units are mass units, dimension units length units; a pack level's unit is a count unit | here (422) |
| the base level exists for every item with a base unit and equals ``base_unit_id`` | created here + ``guard_item_unit`` / ``guard_items_base_unit`` triggers |
| a level's structure never changes; a contained level cannot retire before its container | ``guard_item_unit`` (+ clean errors here) |
| one default sales / purchase level; one preferred vendor; one primary code per (level, kind) | cleared here + partial unique indexes |
| a scannable code resolves to one (item, level); GTIN/EAN/UPC/ISBN check digits valid | here (409 / 422) + ``uq_item_identifiers_scannable`` |
| a vendor is a VENDOR party | ``parties.mixins.assert_role`` |
| a component never makes an item contain itself | ``guard_item_component_cycle`` (mapped to 422) |
| a variant's axis values are the product's axes, one option each, options of their attribute | here + composite FK |
| fields Zoho feeds are read-only on a linked item (until push, plan 05 §6) | ``ZOHO_OWNED_ITEM_FIELDS`` (409) |
| an item in use (a component of another item; later: lines, ledger, batches) is never deleted | here (409 ``catalogue_in_use``) |
| concurrent edits never overwrite each other | ``row_version`` (409) |

Taxes, accounts, categories, custom fields, tags, documents and comments of an item are written through
their own modules (owner type ``item``); this service never forks them.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.catalogue import units as unit_math
from app.modules.catalogue.crud import items as crud
from app.modules.catalogue.crud import masters as masters_crud
from app.modules.catalogue.enums import Composition, IdentifierKind, ItemStatus, TrackMode, UnitClass
from app.modules.catalogue.errors import (
    CatalogueInUseError,
    CatalogueRuleError,
    ZohoOwnedFieldError,
    require_organization,
)
from app.modules.catalogue.model import (
    Attribute,
    AttributeOption,
    Item,
    ItemAttributeValue,
    ItemComponent,
    ItemGroup,
    ItemIdentifier,
    ItemMerchandising,
    ItemSalesChannel,
    ItemUnit,
    ItemVendor,
    PackagingType,
    Product,
    ProductAttribute,
    SalesChannel,
    Unit,
)
from app.modules.catalogue.schema.items import (
    AttributeValueIn,
    BaseUnitChange,
    ChannelIn,
    ComponentIn,
    IdentifierIn,
    ItemCreate,
    ItemUnitCreate,
    ItemUnitRetire,
    ItemUnitUpdate,
    ItemUpdate,
    MerchandisingIn,
    ProductCreate,
    ProductUpdate,
    VendorIn,
)

logger = structlog.get_logger("app.catalogue.items")

#: Columns the (phase-3) Zoho ``items`` adapter feeds — read-only on a linked item until push exists.
ZOHO_OWNED_ITEM_FIELDS: frozenset[str] = frozenset({
    "name", "sku", "description", "purchase_description", "product_type", "status", "sales_rate", "purchase_rate",
    "mrp", "hsn_or_sac", "is_taxable", "can_be_sold", "can_be_purchased", "is_inventory_tracked", "track_mode",
    "reorder_level_base", "brand_id", "manufacturer_id", "product_id", "length", "width", "height", "net_weight",
    "weight_unit_id", "dimension_unit_id", "base_unit_id",
})

_LEVEL_FLAG_DEFAULTS = ("is_default_sales", "is_default_purchase")


# ── helpers ──────────────────────────────────────────────────────────────────

def _plain(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
                            data={"current_row_version": row.row_version})


def _db_hint(exc: DBAPIError) -> str | None:
    """The HINT a catalogue trigger raised (e.g. ``catalogue_component_cycle``), if any."""
    cause: Any = exc.orig
    for _ in range(4):
        hint = getattr(cause, "hint", None)
        if hint:
            return str(hint)
        cause = getattr(cause, "__cause__", None)
        if cause is None:
            break
    return None


async def _flush(db: AsyncSession) -> None:
    """Flush, turning a catalogue trigger's refusal into a clean 422/409 instead of a 500."""
    try:
        await db.flush()
    except DBAPIError as exc:
        hint = _db_hint(exc)
        if hint and hint.startswith("catalogue_"):
            message = str(getattr(exc.orig, "args", [exc])[0]).split("\n")[0]
            raise CatalogueRuleError(message.split(": ", 1)[-1], data={"rule": hint}) from exc
        raise


async def _audit(db: AsyncSession, action: str, item: Item | Product, actor_id: int | None, **payload: Any) -> None:
    await record_activity(db, action=action, actor_id=actor_id, subject_type=type(item).__name__,
                          subject_id=str(item.uuid), **payload)


async def _in_org(db: AsyncSession, model: type, row_id: int | None, organization_id: int, field: str) -> Any:
    if row_id is None:
        return None
    row = await masters_crud.get_by_id(db, model, row_id, organization_id=organization_id)
    if row is None:
        raise CatalogueRuleError(f"{field}: {model.__name__} {row_id} does not exist in this organization",
                                 data={"field": field, "id": row_id})
    return row


async def _unit(db: AsyncSession, unit_id: int | None, organization_id: int, field: str,
                classes: Iterable[UnitClass] | None = None) -> Unit | None:
    unit = await _in_org(db, Unit, unit_id, organization_id, field)
    if unit is not None and classes is not None:
        allowed = {c.value for c in classes}
        if unit.unit_class not in allowed:
            raise CatalogueRuleError(
                f"{field}: '{unit.code}' is a {unit.unit_class} unit; expected {' or '.join(sorted(allowed))}",
                data={"field": field, "unit_class": unit.unit_class})
    return unit


async def _brand_and_maker(db: AsyncSession, values: dict, organization_id: int) -> None:
    from app.modules.brands.model import Brand
    from app.modules.manufacturers.model import Manufacturer

    if values.get("brand_id") is not None:
        await _in_org(db, Brand, values["brand_id"], organization_id, "brand_id")
    if values.get("manufacturer_id") is not None:
        await _in_org(db, Manufacturer, values["manufacturer_id"], organization_id, "manufacturer_id")


def _check_policy(values: dict) -> None:
    """The item rules the database also CHECKs — refused here first with a readable 422."""
    track = values.get("track_mode", "none")
    if track in (TrackMode.SERIAL.value, TrackMode.BATCH_SERIAL.value):
        raise CatalogueRuleError("Serial-number tracking is not available yet (plan 04 §8)", data={"field": "track_mode"})
    if track != "none" and not values.get("is_inventory_tracked", True):
        raise CatalogueRuleError("Lot tracking needs inventory tracking", data={"field": "track_mode"})
    if values.get("expiry_tracked") and track not in ("batch", "batch_serial"):
        raise CatalogueRuleError("Expiry tracking needs batch tracking", data={"field": "expiry_tracked"})
    if values.get("composition") == Composition.KIT.value and values.get("is_inventory_tracked", True):
        raise CatalogueRuleError("A kit has no stock of its own (its components move): set is_inventory_tracked false",
                                 data={"field": "composition"})
    if not values.get("can_be_sold", True) and not values.get("can_be_purchased", True) \
            and values.get("status") not in ("inactive", "discontinued"):
        raise CatalogueRuleError("An active item must be sellable or purchasable", data={"field": "can_be_sold"})
    lo, hi = values.get("minimum_order_qty_base"), values.get("maximum_order_qty_base")
    if lo is not None and hi is not None and hi < lo:
        raise CatalogueRuleError("maximum_order_qty_base is below minimum_order_qty_base", data={"field": "maximum_order_qty_base"})
    tmin, tmax = values.get("storage_temp_min_c"), values.get("storage_temp_max_c")
    if tmin is not None and tmax is not None and tmax < tmin:
        raise CatalogueRuleError("storage_temp_max_c is below storage_temp_min_c", data={"field": "storage_temp_max_c"})


async def _check_references(db: AsyncSession, values: dict, organization_id: int) -> None:
    await _brand_and_maker(db, values, organization_id)
    await _in_org(db, ItemGroup, values.get("item_group_id"), organization_id, "item_group_id")
    await _in_org(db, Product, values.get("product_id"), organization_id, "product_id")
    await _unit(db, values.get("weight_unit_id"), organization_id, "weight_unit_id", (UnitClass.MASS,))
    await _unit(db, values.get("dimension_unit_id"), organization_id, "dimension_unit_id", (UnitClass.LENGTH,))


async def _unique_sku_code(db: AsyncSession, organization_id: int, values: dict, exclude_id: int | None = None) -> None:
    if values.get("sku"):
        values["sku"] = values["sku"].strip()
        other = await crud.find_item(db, organization_id=organization_id, sku_normalized=values["sku"].upper())
        if other is not None and other.id != exclude_id:
            raise ConflictError(f"SKU '{values['sku']}' already belongs to '{other.name}'", data={"sku": values["sku"]})
    if values.get("code"):
        values["code"] = values["code"].strip()
        other = await crud.find_item(db, organization_id=organization_id, code=values["code"])
        if other is not None and other.id != exclude_id:
            raise ConflictError(f"Item code '{values['code']}' already exists", data={"code": values["code"]})


def _clean_aliases(aliases: list[str] | None) -> list[str] | None:
    if aliases is None:
        return None
    seen: dict[str, str] = {}
    for alias in aliases:
        text = re.sub(r"\s+", " ", alias).strip()
        if text and text.lower() not in seen:
            seen[text.lower()] = text
    return list(seen.values()) or None


def _guard_zoho_owned(item: Item, changes: Iterable[str]) -> None:
    if item.zoho_id is None:
        return
    blocked = sorted(set(changes) & ZOHO_OWNED_ITEM_FIELDS)
    if blocked:
        raise ZohoOwnedFieldError(
            f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for '{item.name}' "
            f"(zoho_id {item.zoho_id}); change {'it' if len(blocked) == 1 else 'them'} in Zoho — the next sync "
            "brings it here", data={"zoho_owned": blocked})


# ── items ────────────────────────────────────────────────────────────────────

async def list_items(db: AsyncSession, **kw: Any):
    organization_id = await require_organization(db)
    return await crud.list_items(db, organization_id=organization_id, **kw)


async def get_item(db: AsyncSession, ref: str, *, fat: bool = True) -> Item:
    organization_id = await require_organization(db)
    item = await crud.get_item(db, ref, organization_id=organization_id, fat=fat)
    if item is None:
        raise NotFoundError(f"Item '{ref}' not found")
    return item


async def _reload(db: AsyncSession, item: Item) -> Item:
    db.expire(item)
    return await crud.get_item(db, str(item.id), organization_id=item.organization_id) or item


async def create_item(db: AsyncSession, body: ItemCreate, *, actor_id: int | None = None) -> Item:
    organization_id = await require_organization(db)
    nested = {"merchandising", "base_level", "units", "identifiers", "vendors", "channels", "attribute_values",
              "components"}
    values = _plain(body.model_dump(exclude_none=True, exclude=nested))
    values["name"] = body.name.strip()
    if values["status"] not in (ItemStatus.DRAFT.value, ItemStatus.ACTIVE.value):
        raise CatalogueRuleError("A new item starts as draft or active", data={"field": "status"})
    if values.get("country_of_origin"):
        values["country_of_origin"] = values["country_of_origin"].upper()
    if "alias_names" in values:
        values["alias_names"] = _clean_aliases(values["alias_names"])
    _check_policy(values)
    await _check_references(db, values, organization_id)
    await _unit(db, body.base_unit_id, organization_id, "base_unit_id")
    await _unique_sku_code(db, organization_id, values)

    item = Item(**values, organization_id=organization_id)
    db.add(item)
    await _flush(db)

    # base level first, then the declared levels in order (each names an EARLIER level by its unit)
    base_fields = body.base_level.model_dump() if body.base_level else {}
    base = await _add_level(db, item, unit_id=body.base_unit_id, contents=None, qty=None,
                            fields=base_fields | {"is_default_sales": base_fields.get("is_default_sales", not body.units),
                                                  "is_default_purchase": base_fields.get("is_default_purchase", not body.units)})
    by_unit = {body.base_unit_id: base}
    for spec in body.units:
        contents = by_unit.get(spec.contains_unit_id)
        if contents is None:
            raise CatalogueRuleError(f"units: unit {spec.contains_unit_id} is not the base unit or an earlier level",
                                     data={"field": "units", "contains_unit_id": spec.contains_unit_id})
        if spec.unit_id in by_unit:
            raise CatalogueRuleError(f"units: unit {spec.unit_id} is listed twice", data={"field": "units"})
        fields = spec.model_dump(exclude={"unit_id", "contains_unit_id", "contents_qty"})
        by_unit[spec.unit_id] = await _add_level(db, item, unit_id=spec.unit_id, contents=contents,
                                                 qty=spec.contents_qty, fields=fields)

    for code in body.identifiers:
        level = by_unit.get(code.unit_id) if code.unit_id is not None else None
        if code.unit_id is not None and level is None:
            raise CatalogueRuleError(f"identifiers: unit {code.unit_id} is not a level of this item",
                                     data={"field": "identifiers"})
        await _add_identifier(db, item, IdentifierIn(kind=code.kind, value=code.value,
                                                     item_unit_id=level.id if level else None,
                                                     is_primary=code.is_primary))
    if body.merchandising is not None:
        await _put_merchandising(db, item, body.merchandising)
    if body.vendors:
        await _replace_vendors(db, item, body.vendors)
    if body.channels:
        await _replace_channels(db, item, body.channels)
    if body.attribute_values:
        await _replace_attribute_values(db, item, body.attribute_values)
    if body.components:
        await _replace_components(db, item, body.components)

    await _audit(db, "catalogue_item_created", item, actor_id,
                 changes={"after": {"name": item.name, "sku": item.sku, "levels": len(by_unit)}})
    logger.info("catalogue.item.created", item_id=item.id, organization_id=organization_id, levels=len(by_unit))
    return await _reload(db, item)


async def update_item(db: AsyncSession, ref: str, body: ItemUpdate, *, actor_id: int | None = None) -> Item:
    item = await get_item(db, ref, fat=False)
    _check_version(item, body.row_version, f"Item '{item.name}'")
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    _guard_zoho_owned(item, changes)
    if "name" in changes and changes["name"]:
        changes["name"] = changes["name"].strip()
    if changes.get("country_of_origin"):
        changes["country_of_origin"] = changes["country_of_origin"].upper()
    if "alias_names" in changes:
        changes["alias_names"] = _clean_aliases(changes["alias_names"])
    merged = {c.key: getattr(item, c.key) for c in Item.__table__.columns if c.key in {
        "track_mode", "is_inventory_tracked", "expiry_tracked", "composition", "can_be_sold", "can_be_purchased",
        "status", "minimum_order_qty_base", "maximum_order_qty_base", "storage_temp_min_c", "storage_temp_max_c"}}
    merged.update(changes)
    _check_policy(merged)
    await _check_references(db, changes, item.organization_id)
    await _unique_sku_code(db, item.organization_id, changes, exclude_id=item.id)
    if "track_mode" in changes and changes["track_mode"] != item.track_mode and item.track_mode != "none":
        # phase 4: refused while batches with stock exist (409 tracking_locked)
        pass
    for field, value in changes.items():
        setattr(item, field, value)
    await _flush(db)
    await _audit(db, "catalogue_item_updated", item, actor_id, changes={"after": {k: str(v) for k, v in changes.items()}})
    return await _reload(db, item)


async def set_status(db: AsyncSession, ref: str, status: ItemStatus, *, reason: str | None,
                     actor_id: int | None = None) -> Item:
    item = await get_item(db, ref, fat=False)
    _guard_zoho_owned(item, {"status"} if status in (ItemStatus.ACTIVE, ItemStatus.INACTIVE) else set())
    if status == ItemStatus.ACTIVE:
        item.reactivate()
    elif status == ItemStatus.INACTIVE:
        item.deactivate(reason=reason, by=actor_id)
    item.status = status.value
    await _flush(db)
    await _audit(db, f"catalogue_item_{status.value}", item, actor_id, context={"reason": reason})
    return await _reload(db, item)


async def delete_item(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    item = await get_item(db, ref, fat=False)
    if await crud.is_component_somewhere(db, item.id):
        raise CatalogueInUseError(f"'{item.name}' is a component of another item; deactivate it instead",
                                  data={"item": str(item.uuid)})
    for model, column in ((ItemIdentifier, "item_id"), (ItemSalesChannel, "item_id"), (ItemVendor, "item_id"),
                          (ItemAttributeValue, "item_id"), (ItemComponent, "parent_item_id"),
                          (ItemMerchandising, "item_id")):
        for row in await crud.children(db, model, item.id, column):
            row.soft_delete(reason=f"item {item.uuid} deleted", by=actor_id)
    item.soft_delete(reason=reason, by=actor_id)
    await _flush(db)
    await _audit(db, "catalogue_item_deleted", item, actor_id, context={"reason": reason})


async def change_base_unit(db: AsyncSession, ref: str, body: BaseUnitChange, *, actor_id: int | None = None) -> Item:
    """Only while the item has nothing but its base level (no packs, no level codes; later: no stock, no lines)."""
    item = await get_item(db, ref, fat=False)
    _check_version(item, body.row_version, f"Item '{item.name}'")
    _guard_zoho_owned(item, {"base_unit_id"})
    await _unit(db, body.base_unit_id, item.organization_id, "base_unit_id")
    levels = [lv for lv in await crud.item_levels(db, item.id) if lv.deleted_at is None]
    if any(not lv.is_base for lv in levels) or any(i.item_unit_id for i in await crud.children(db, ItemIdentifier, item.id)):
        raise ConflictError("The base unit can change only while the item has no pack levels (retire them first)",
                            data={"code": "base_unit_locked"})
    for level in levels:
        level.soft_delete(reason="base unit changed", by=actor_id)
    await _flush(db)
    item.base_unit_id = body.base_unit_id
    await _flush(db)
    await _add_level(db, item, unit_id=body.base_unit_id, contents=None, qty=None,
                     fields={"is_default_sales": True, "is_default_purchase": True})
    await _audit(db, "catalogue_item_base_unit_changed", item, actor_id, changes={"after": {"base_unit_id": body.base_unit_id}})
    return await _reload(db, item)


# ── packaging hierarchy ──────────────────────────────────────────────────────

async def _level_refs(db: AsyncSession, item: Item, fields: dict) -> None:
    await _in_org(db, PackagingType, fields.get("packaging_type_id"), item.organization_id, "packaging_type_id")
    await _unit(db, fields.get("weight_unit_id"), item.organization_id, "weight_unit_id", (UnitClass.MASS,))
    await _unit(db, fields.get("dimension_unit_id"), item.organization_id, "dimension_unit_id", (UnitClass.LENGTH,))


async def _add_level(db: AsyncSession, item: Item, *, unit_id: int, contents: ItemUnit | None,
                     qty: Decimal | None, fields: dict) -> ItemUnit:
    is_base = contents is None
    if not is_base:
        await _unit(db, unit_id, item.organization_id, "unit_id", (UnitClass.COUNT,))
        if contents.valid_to is not None or contents.deleted_at is not None:
            raise CatalogueRuleError("The contents level is retired", data={"field": "contents_item_unit_id"})
    if await crud.current_level_for_unit(db, item.id, unit_id) is not None:
        raise ConflictError("This unit is already a current level of the item", data={"unit_id": unit_id})
    await _level_refs(db, item, fields)
    level = ItemUnit(
        item_id=item.id, organization_id=item.organization_id, unit_id=unit_id, is_base=is_base,
        contents_item_unit_id=None if is_base else contents.id, contents_qty=None if is_base else qty,
        base_factor=Decimal(1) if is_base else Decimal(qty) * Decimal(contents.base_factor),
        **{k: v for k, v in fields.items() if v is not None},
    )
    for column in _LEVEL_FLAG_DEFAULTS:
        if fields.get(column):
            await crud.clear_level_defaults(db, item.id, column, keep_id=None)
    db.add(level)
    await _flush(db)
    await db.refresh(level)              # base_factor is authoritative from the trigger
    return level


async def list_levels(db: AsyncSession, ref: str) -> list[ItemUnit]:
    item = await get_item(db, ref, fat=False)
    return await crud.item_levels(db, item.id)


async def _get_level(db: AsyncSession, item: Item, level_ref: str) -> ItemUnit:
    level = await crud.get_level(db, item.id, level_ref)
    if level is None:
        raise NotFoundError(f"Level '{level_ref}' of '{item.name}' not found")
    return level


async def add_level(db: AsyncSession, ref: str, body: ItemUnitCreate, *, actor_id: int | None = None) -> ItemUnit:
    item = await get_item(db, ref, fat=False)
    contents = await _get_level(db, item, str(body.contents_item_unit_id))
    level = await _add_level(db, item, unit_id=body.unit_id, contents=contents, qty=body.contents_qty,
                             fields=body.model_dump(exclude={"unit_id", "contents_item_unit_id", "contents_qty"}))
    await _audit(db, "catalogue_item_level_added", item, actor_id,
                 changes={"after": {"unit_id": body.unit_id, "contents_qty": str(body.contents_qty),
                                    "base_factor": str(level.base_factor)}})
    return await crud.get_level(db, item.id, str(level.id)) or level


async def update_level(db: AsyncSession, ref: str, level_ref: str, body: ItemUnitUpdate,
                       *, actor_id: int | None = None) -> ItemUnit:
    item = await get_item(db, ref, fat=False)
    level = await _get_level(db, item, level_ref)
    _check_version(level, body.row_version, "Level")
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version"}))
    await _level_refs(db, item, changes)
    for column in _LEVEL_FLAG_DEFAULTS:
        if changes.get(column):
            await crud.clear_level_defaults(db, item.id, column, keep_id=level.id)
    for field, value in changes.items():
        setattr(level, field, value)
    await _flush(db)
    await _audit(db, "catalogue_item_level_updated", item, actor_id, changes={"after": {k: str(v) for k, v in changes.items()}})
    return await crud.get_level(db, item.id, str(level.id)) or level


async def retire_level(db: AsyncSession, ref: str, level_ref: str, body: ItemUnitRetire,
                       *, actor_id: int | None = None) -> ItemUnit | None:
    """Retire a level (``valid_to``), optionally creating its replacement in the same call."""
    item = await get_item(db, ref, fat=False)
    level = await _get_level(db, item, level_ref)
    if level.is_base:
        raise CatalogueRuleError("The base level cannot be retired; change the base unit instead",
                                 data={"code": "base_level"})
    if level.valid_to is not None:
        raise ConflictError("This level is already retired")
    if await crud.level_is_contained(db, level.id):
        raise ConflictError("A current level still contains this one; retire the outer level first",
                            data={"code": "item_unit_in_use"})
    today = dt.date.today()
    level.valid_to = today if today > level.valid_from else level.valid_from + dt.timedelta(days=1)
    level.is_default_sales = level.is_default_purchase = False
    await _flush(db)
    replacement = None
    if body.replacement is not None:
        contents = await _get_level(db, item, str(body.replacement.contents_item_unit_id))
        replacement = await _add_level(
            db, item, unit_id=body.replacement.unit_id, contents=contents, qty=body.replacement.contents_qty,
            fields=body.replacement.model_dump(exclude={"unit_id", "contents_item_unit_id", "contents_qty"}))
    await _audit(db, "catalogue_item_level_retired", item, actor_id,
                 context={"reason": body.reason, "level": str(level.uuid),
                          "replacement": str(replacement.uuid) if replacement else None})
    return replacement


async def convert(db: AsyncSession, ref: str, *, qty: Decimal | None, from_id: int | None, to_id: int | None,
                  qty_base: Decimal | None) -> dict:
    item = await get_item(db, ref, fat=False)
    levels = await crud.item_levels(db, item.id)
    by_id = {lv.id: lv for lv in levels}
    if qty_base is not None:
        parts = unit_math.breakdown(qty_base, levels)
        return {"breakdown": [{"item_unit_id": lv.id if lv else 0, "unit_code": lv.unit.code if lv else "base",
                               "count": count} for lv, count in parts]}
    if from_id not in by_id or to_id not in by_id:
        raise CatalogueRuleError("Both levels must belong to this item", data={"field": "from_item_unit_id"})
    return {"quantity": unit_math.convert(qty, by_id[from_id], by_id[to_id])}


# ── identifiers ──────────────────────────────────────────────────────────────

async def _add_identifier(db: AsyncSession, item: Item, body: IdentifierIn, *, source: str = "local") -> ItemIdentifier:
    kind = IdentifierKind(body.kind)
    value = body.value.strip()
    normalized = "".join(value.split()).upper()
    if not unit_math.check_digit_ok(kind.value, normalized):
        raise CatalogueRuleError(f"'{value}' is not a valid {kind.value.upper()} (shape or check digit)",
                                 data={"code": "invalid_gtin", "kind": kind.value, "value": value})
    if body.item_unit_id is not None:
        await _get_level(db, item, str(body.item_unit_id))
    if kind.is_scannable:
        other = await crud.find_identifier(db, item.organization_id, normalized)
        if other is not None:
            raise ConflictError(f"'{value}' already identifies another item or level",
                                data={"code": "duplicate_identifier", "item_id": other.item_id})
    if body.is_primary:
        for row in await crud.children(db, ItemIdentifier, item.id):
            if row.is_primary and row.kind == kind.value and row.item_unit_id == body.item_unit_id:
                row.is_primary = False
    row = ItemIdentifier(item_id=item.id, organization_id=item.organization_id, item_unit_id=body.item_unit_id,
                         kind=kind.value, value=value, is_primary=body.is_primary, source=source)
    db.add(row)
    await _flush(db)
    return row


async def add_identifier(db: AsyncSession, ref: str, body: IdentifierIn, *, actor_id: int | None = None) -> ItemIdentifier:
    item = await get_item(db, ref, fat=False)
    row = await _add_identifier(db, item, body)
    await _audit(db, "catalogue_item_identifier_added", item, actor_id, changes={"after": {"kind": row.kind, "value": row.value}})
    return row


async def list_identifiers(db: AsyncSession, ref: str) -> list[ItemIdentifier]:
    item = await get_item(db, ref, fat=False)
    return await crud.children(db, ItemIdentifier, item.id)


async def delete_identifier(db: AsyncSession, ref: str, code_ref: str, *, reason: str, actor_id: int | None = None) -> None:
    item = await get_item(db, ref, fat=False)
    row = await crud.get_identifier(db, item.id, code_ref)
    if row is None:
        raise NotFoundError(f"Code '{code_ref}' of '{item.name}' not found")
    _guard_zoho_owned(item, {"sku"} if row.source == "zoho" else set())
    row.soft_delete(reason=reason, by=actor_id)
    await _flush(db)
    await _audit(db, "catalogue_item_identifier_deleted", item, actor_id, context={"reason": reason, "value": row.value})


async def lookup(db: AsyncSession, code: str) -> dict:
    organization_id = await require_organization(db)
    normalized = "".join(code.split()).upper()
    row = await crud.lookup_identifier(db, organization_id, normalized)
    if row is None:
        item = await crud.find_item(db, organization_id=organization_id, sku_normalized=normalized)
        if item is None:
            raise NotFoundError(f"No item or level carries the code '{code}'")
        return {"item_id": item.id, "item_uuid": item.uuid, "sku": item.sku, "name": item.name,
                "item_unit_id": None, "unit_code": None, "base_factor": None, "identifier_kind": "sku"}
    item = await crud.get_item_by_id(db, row.item_id, organization_id=organization_id)
    level = await crud.get_level(db, row.item_id, str(row.item_unit_id)) if row.item_unit_id else None
    return {"item_id": item.id, "item_uuid": item.uuid, "sku": item.sku, "name": item.name,
            "item_unit_id": level.id if level else None, "unit_code": level.unit.code if level else None,
            "base_factor": level.base_factor if level else None, "identifier_kind": row.kind}


# ── merchandising ────────────────────────────────────────────────────────────

async def _put_merchandising(db: AsyncSession, item: Item, body: MerchandisingIn) -> ItemMerchandising:
    values = body.model_dump()
    if values.get("slug"):
        from sqlalchemy import select

        clash = await db.scalar(select(ItemMerchandising).where(
            ItemMerchandising.organization_id == item.organization_id, ItemMerchandising.slug == values["slug"],
            ItemMerchandising.item_id != item.id).limit(1))
        if clash is not None:
            raise ConflictError(f"Slug '{values['slug']}' is already used by another item", data={"slug": values["slug"]})
    row = await crud.merchandising(db, item.id)
    if row is None:
        row = ItemMerchandising(item_id=item.id, organization_id=item.organization_id, **values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    await _flush(db)
    return row


async def put_merchandising(db: AsyncSession, ref: str, body: MerchandisingIn, *, actor_id: int | None = None) -> Item:
    item = await get_item(db, ref, fat=False)
    await _put_merchandising(db, item, body)
    await _audit(db, "catalogue_item_merchandising_updated", item, actor_id)
    return await _reload(db, item)


# ── replace-set children ─────────────────────────────────────────────────────

def _retire(row: Any, actor_id: int | None, reason: str) -> None:
    if hasattr(row, "valid_to"):
        today = dt.date.today()
        row.valid_to = today if today > row.valid_from else row.valid_from + dt.timedelta(days=1)
    else:
        row.soft_delete(reason=reason, by=actor_id)


async def _replace_vendors(db: AsyncSession, item: Item, wanted: Sequence[VendorIn], actor_id: int | None = None) -> None:
    from app.modules.parties.mixins import assert_role
    from app.modules.parties.model import Party

    if sum(1 for v in wanted if v.is_preferred) > 1:
        raise CatalogueRuleError("Only one vendor can be preferred", data={"field": "vendors"})
    if len({v.vendor_id for v in wanted}) != len(wanted):
        raise CatalogueRuleError("A vendor is listed twice", data={"field": "vendors"})
    current = {row.vendor_id: row for row in await crud.children(db, ItemVendor, item.id)}
    for spec in wanted:
        party = await _in_org(db, Party, spec.vendor_id, item.organization_id, "vendor_id")
        try:
            assert_role(party, "vendor")
        except Exception as exc:
            raise CatalogueRuleError(str(exc), data={"field": "vendor_id", "party_type": party.party_type}) from exc
        if spec.purchase_item_unit_id is not None:
            await _get_level(db, item, str(spec.purchase_item_unit_id))
    for vendor_id, row in current.items():          # clear first: the preferred slot is unique
        if vendor_id not in {v.vendor_id for v in wanted}:
            row.soft_delete(reason="removed from item vendors", by=actor_id)
        else:
            row.is_preferred = False
    await _flush(db)
    for spec in wanted:
        values = spec.model_dump()
        row = current.get(spec.vendor_id)
        if row is None:
            db.add(ItemVendor(item_id=item.id, organization_id=item.organization_id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    await _flush(db)


async def _replace_channels(db: AsyncSession, item: Item, wanted: Sequence[ChannelIn], actor_id: int | None = None) -> None:
    if len({c.sales_channel_id for c in wanted}) != len(wanted):
        raise CatalogueRuleError("A channel is listed twice", data={"field": "channels"})
    current = {row.sales_channel_id: row for row in await crud.children(db, ItemSalesChannel, item.id)
               if row.valid_to is None}
    for spec in wanted:
        await _in_org(db, SalesChannel, spec.sales_channel_id, item.organization_id, "sales_channel_id")
        if spec.price_item_unit_id is not None:
            await _get_level(db, item, str(spec.price_item_unit_id))
    for channel_id, row in current.items():
        if channel_id not in {c.sales_channel_id for c in wanted}:
            _retire(row, actor_id, "removed from item channels")
    for spec in wanted:
        values = spec.model_dump()
        row = current.get(spec.sales_channel_id)
        if row is None:
            db.add(ItemSalesChannel(item_id=item.id, organization_id=item.organization_id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    await _flush(db)


async def _replace_attribute_values(db: AsyncSession, item: Item, wanted: Sequence[AttributeValueIn],
                                    actor_id: int | None = None) -> None:
    if len({v.attribute_id for v in wanted}) != len(wanted):
        raise CatalogueRuleError("An attribute is listed twice", data={"field": "attribute_values"})
    if wanted and item.product_id is None:
        raise CatalogueRuleError("Axis values belong to a variant: set product_id first", data={"field": "attribute_values"})
    axes = {a.attribute_id for a in await crud.product_axes(db, item.product_id)} if item.product_id else set()
    for spec in wanted:
        await _in_org(db, Attribute, spec.attribute_id, item.organization_id, "attribute_id")
        option = await _in_org(db, AttributeOption, spec.attribute_option_id, item.organization_id, "attribute_option_id")
        if option.attribute_id != spec.attribute_id:
            raise CatalogueRuleError("The option belongs to another attribute", data={"field": "attribute_option_id"})
        if spec.attribute_id not in axes:
            raise CatalogueRuleError(f"Attribute {spec.attribute_id} is not an axis of the item's product",
                                     data={"field": "attribute_id"})
    current = {row.attribute_id: row for row in await crud.children(db, ItemAttributeValue, item.id)}
    for attribute_id, row in current.items():
        if attribute_id not in {v.attribute_id for v in wanted}:
            row.soft_delete(reason="axis value removed", by=actor_id)
    for spec in wanted:
        row = current.get(spec.attribute_id)
        if row is None:
            db.add(ItemAttributeValue(item_id=item.id, organization_id=item.organization_id,
                                      attribute_id=spec.attribute_id, attribute_option_id=spec.attribute_option_id))
        else:
            row.attribute_option_id = spec.attribute_option_id
    await _flush(db)


async def _replace_components(db: AsyncSession, item: Item, wanted: Sequence[ComponentIn],
                              actor_id: int | None = None) -> None:
    if wanted and item.composition == Composition.NONE.value:
        roles = {c.role.value for c in wanted}
        if roles - {"box_content", "packaging_material"}:
            raise CatalogueRuleError("Assembly components and kit members need composition 'assembly' or 'kit'",
                                     data={"field": "components"})
    keys = [(c.component_item_id, c.role.value) for c in wanted]
    if len(set(keys)) != len(keys):
        raise CatalogueRuleError("A component is listed twice with the same role", data={"field": "components"})
    for spec in wanted:
        if spec.component_item_id == item.id:
            raise CatalogueRuleError("An item cannot contain itself", data={"field": "component_item_id"})
        component = await _in_org(db, Item, spec.component_item_id, item.organization_id, "component_item_id")
        if spec.component_item_unit_id is not None:
            await _get_level(db, component, str(spec.component_item_unit_id))
    current = {(row.component_item_id, row.role): row for row in await crud.children(db, ItemComponent, item.id, "parent_item_id")
               if row.valid_to is None}
    for key, row in current.items():
        if key not in set(keys):
            _retire(row, actor_id, "removed from components")
    await _flush(db)
    for spec in wanted:
        values = _plain(spec.model_dump())
        row = current.get((spec.component_item_id, spec.role.value))
        if row is None:
            db.add(ItemComponent(parent_item_id=item.id, organization_id=item.organization_id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
    await _flush(db)


async def replace_children(db: AsyncSession, ref: str, kind: str, wanted: Sequence[Any],
                           *, actor_id: int | None = None) -> Item:
    item = await get_item(db, ref, fat=False)
    handler = {"vendors": _replace_vendors, "channels": _replace_channels,
               "attributes": _replace_attribute_values, "components": _replace_components}[kind]
    await handler(db, item, wanted, actor_id)
    await _audit(db, f"catalogue_item_{kind}_replaced", item, actor_id, changes={"after": {"count": len(wanted)}})
    return await _reload(db, item)


# ── products ─────────────────────────────────────────────────────────────────

async def _set_axes(db: AsyncSession, product: Product, attribute_ids: Sequence[int], actor_id: int | None) -> None:
    if len(set(attribute_ids)) != len(attribute_ids):
        raise CatalogueRuleError("An axis is listed twice", data={"field": "attribute_ids"})
    for attribute_id in attribute_ids:
        await _in_org(db, Attribute, attribute_id, product.organization_id, "attribute_ids")
    for row in await crud.product_axes(db, product.id):
        row.soft_delete(reason="axes replaced", by=actor_id)
    await _flush(db)
    for position, attribute_id in enumerate(attribute_ids, start=1):
        db.add(ProductAttribute(product_id=product.id, organization_id=product.organization_id,
                                attribute_id=attribute_id, position=position))
    await _flush(db)


async def list_products(db: AsyncSession, **kw: Any):
    organization_id = await require_organization(db)
    return await crud.list_products(db, organization_id=organization_id, **kw)


async def get_product(db: AsyncSession, ref: str) -> Product:
    organization_id = await require_organization(db)
    product = await crud.get_product(db, ref, organization_id=organization_id)
    if product is None:
        raise NotFoundError(f"Product '{ref}' not found")
    return product


async def product_detail(db: AsyncSession, product: Product) -> dict:
    return {"attribute_ids": [a.attribute_id for a in await crud.product_axes(db, product.id)],
            "variants": await crud.product_variants(db, product.id)}


async def _product_refs(db: AsyncSession, values: dict, organization_id: int) -> None:
    await _brand_and_maker(db, values, organization_id)
    await _in_org(db, ItemGroup, values.get("item_group_id"), organization_id, "item_group_id")
    await _unit(db, values.get("default_unit_id"), organization_id, "default_unit_id")
    for column in ("slug", "code"):
        if values.get(column):
            clash = await crud.find_product(db, organization_id=organization_id, **{column: values[column]})
            if clash is not None and clash.id != values.get("_id"):
                raise ConflictError(f"Product {column} '{values[column]}' already exists", data={column: values[column]})


async def create_product(db: AsyncSession, body: ProductCreate, *, actor_id: int | None = None) -> Product:
    organization_id = await require_organization(db)
    values = body.model_dump(exclude_none=True, exclude={"attribute_ids"})
    values["name"] = body.name.strip()
    await _product_refs(db, values, organization_id)
    product = Product(**values, organization_id=organization_id)
    db.add(product)
    await _flush(db)
    await _set_axes(db, product, body.attribute_ids, actor_id)
    await _audit(db, "catalogue_product_created", product, actor_id, changes={"after": {"name": product.name}})
    return product


async def update_product(db: AsyncSession, ref: str, body: ProductUpdate, *, actor_id: int | None = None) -> Product:
    product = await get_product(db, ref)
    _check_version(product, body.row_version, f"Product '{product.name}'")
    changes = _plain(body.model_dump(exclude_unset=True, exclude={"row_version", "attribute_ids"}))
    await _product_refs(db, changes | {"_id": product.id}, product.organization_id)
    if body.attribute_ids is not None:
        if await crud.product_variants(db, product.id):
            raise ConflictError("The axes can change only while the product has no variants",
                                data={"code": "product_has_variants"})
        await _set_axes(db, product, body.attribute_ids, actor_id)
    for field, value in changes.items():
        setattr(product, field, value)
    await _flush(db)
    await _audit(db, "catalogue_product_updated", product, actor_id, changes={"after": {k: str(v) for k, v in changes.items()}})
    return product


async def delete_product(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    product = await get_product(db, ref)
    if await crud.product_variants(db, product.id):
        raise CatalogueInUseError(f"'{product.name}' has variants; move or delete them first", data={"product": str(product.uuid)})
    for row in await crud.product_axes(db, product.id):
        row.soft_delete(reason=f"product deleted: {reason}", by=actor_id)
    product.soft_delete(reason=reason, by=actor_id)
    await _flush(db)
    await _audit(db, "catalogue_product_deleted", product, actor_id, context={"reason": reason})


async def data_quality(db: AsyncSession) -> dict[str, int]:
    return await crud.data_quality(db, await require_organization(db))
