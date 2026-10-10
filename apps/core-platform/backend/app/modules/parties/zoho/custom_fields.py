"""Zoho ``custom_fields[]`` → ``extfields`` definitions and values, for any owner type.

Zoho sends each field's metadata WITH its value, so definitions are learned from payloads:

* identity = Zoho's immutable ``field_id`` (``zoho_field_id``); a local definition with the same
  ``api_name`` is adopted (its ``zoho_field_id`` set) rather than duplicated;
* ``data_type`` → ``extfields.data_types`` by code; a Zoho type the vocabulary has not seen yet
  (``string``, ``check_box`` …) is added with the storage column it implies — the vocabulary is open by
  design (a new Zoho type is a lookup row, not a migration);
* dropdown options are learned into ``options`` (Zoho sends only the selected one).

Values: every field present with a value is upserted into its typed column; a Zoho-defined field absent
from the array (Zoho omits empty fields) has its value soft-deleted. Values of LOCAL definitions are
never touched. A value that cannot inhabit its column is logged and skipped — one odd value never fails
the record.

This path writes through ``custom_fields.crud`` directly instead of ``custom_fields.service``: the
service is the request path (organization from the request, an activity row per call), and the sync's
history is ``sync.sync_payloads``.
"""

from __future__ import annotations


import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.custom_fields.enums import StorageColumn
from app.modules.custom_fields.errors import CustomFieldRuleError
from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue
from app.modules.custom_fields.service import value_columns
from app.modules.sync.translation import CODECS

logger = structlog.get_logger("app.parties.zoho")

_str, _bool, _int = CODECS["str"].decode, CODECS["bool"].decode, CODECS["int"].decode
_CACHE_KEY = "zoho_custom_field_definitions"
REMOVED_REASON = "zoho:custom_field_absent"

#: Storage of Zoho data types the seeded vocabulary does not name (learned on first sight).
_IMPLIED_STORAGE = {
    "check_box": StorageColumn.VALUE_BOOLEAN, "boolean": StorageColumn.VALUE_BOOLEAN,
    "date": StorageColumn.VALUE_DATE, "date_time": StorageColumn.VALUE_DATE,
    "number": StorageColumn.VALUE_NUMERIC, "decimal": StorageColumn.VALUE_NUMERIC,
    "amount": StorageColumn.VALUE_NUMERIC, "percent": StorageColumn.VALUE_NUMERIC,
    "multiselect": StorageColumn.VALUE_JSON,
}


def _cache(db: AsyncSession) -> dict:
    return db.sync_session.info.setdefault(_CACHE_KEY, {})


async def _data_type(db: AsyncSession, code: str) -> tuple[int, str]:
    cache = _cache(db).setdefault("__types__", {})
    if code in cache:
        return cache[code]
    row = await db.scalar(select(DataType).where(DataType.code == code))
    if row is None:
        storage = _IMPLIED_STORAGE.get(code, StorageColumn.VALUE_TEXT).value
        await db.execute(pg_insert(DataType.__table__).values(
            code=code, label=code.replace("_", " ").title(), storage_column=storage,
            created_by_name="system:zoho-sync",
        ).on_conflict_do_nothing())
        row = await db.scalar(select(DataType).where(DataType.code == code))
        logger.info("parties.zoho.custom_field_type_learned", code=code, storage_column=storage)
    cache[code] = (row.id, str(row.storage_column))
    return cache[code]


async def _definition(db: AsyncSession, owner, owner_type: str, field: dict) -> tuple[int, str, bool] | None:
    """(definition id, storage column, is_active) for a Zoho field, learning/refreshing the definition."""
    zoho_field_id = _str(field.get("field_id") or field.get("customfield_id"))
    api_name = _str(field.get("api_name"))
    if zoho_field_id is None or api_name is None:
        return None
    key = (owner.organization_id, owner_type, zoho_field_id)
    cached = _cache(db).get(key)
    option = None
    if field.get("selected_option_id"):
        option = {"id": str(field["selected_option_id"]), "value": field.get("value"),
                  "color_code": field.get("color_code")}
    if cached is not None and (option is None or option["id"] in cached[3]):
        return cached[:3]

    type_id, storage = await _data_type(db, _str(field.get("data_type")) or "text")
    definition = await db.scalar(select(FieldDefinition).where(
        FieldDefinition.organization_id == owner.organization_id, FieldDefinition.owner_type_code == owner_type,
        FieldDefinition.zoho_field_id == zoho_field_id))
    if definition is None:
        definition = await db.scalar(select(FieldDefinition).where(
            FieldDefinition.organization_id == owner.organization_id, FieldDefinition.owner_type_code == owner_type,
            FieldDefinition.api_name == api_name))
    values = {
        "zoho_field_id": zoho_field_id, "api_name": api_name, "label": _str(field.get("label")) or api_name,
        "sort_order": _int(field.get("index")), "is_active": _bool(field.get("is_active")),
        "show_in_store": _bool(field.get("show_in_store")), "show_in_all_pdf": _bool(field.get("show_in_all_pdf")),
        "edit_on_store": _bool(field.get("edit_on_store")), "is_dependent_field": _bool(field.get("is_dependent_field")),
    }
    if definition is None:
        definition = FieldDefinition(tenant_id=owner.tenant_id, organization_id=owner.organization_id,
                                     owner_type_code=owner_type, data_type_id=type_id, **values)
        db.add(definition)
        logger.info("parties.zoho.custom_field_learned", owner_type=owner_type, api_name=api_name)
    else:
        for column, value in values.items():
            if value is not None and getattr(definition, column) != value:
                setattr(definition, column, value)
        if definition.data_type_id != type_id:
            # The definition's type decides the column; Zoho changed it (rare) — follow Zoho.
            definition.data_type_id = type_id
    options = list(definition.options or [])
    if option is not None and all(o.get("id") != option["id"] for o in options):
        options.append(option)
        definition.options = options
    await db.flush()
    option_ids = {o.get("id") for o in options}
    _cache(db)[key] = (definition.id, storage, definition.is_active is not False, option_ids)
    return definition.id, storage, definition.is_active is not False


async def project_custom_fields(db: AsyncSession, owner, owner_type: str, fields: list[dict]) -> dict[str, int]:
    counts = {"cf_set": 0, "cf_cleared": 0, "cf_skipped": 0}
    existing = {v.field_definition_id: v for v in (await db.scalars(select(FieldValue).where(
        FieldValue.organization_id == owner.organization_id, FieldValue.owner_type_code == owner_type,
        FieldValue.owner_id == owner.id))).all()}

    present: set[int] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        resolved = await _definition(db, owner, owner_type, field)
        if resolved is None:
            continue
        definition_id, storage, _active = resolved
        present.add(definition_id)
        raw = field.get("value")
        value = None if raw in (None, "") else raw
        try:
            columns = value_columns(storage, value)
        except CustomFieldRuleError as exc:
            logger.warning("parties.zoho.custom_field_value_skipped", owner_type=owner_type, owner_id=owner.id,
                           api_name=field.get("api_name"), error=exc.msg)
            counts["cf_skipped"] += 1
            continue
        row = existing.get(definition_id)
        if row is None:
            if value is None:
                continue
            db.add(FieldValue(tenant_id=owner.tenant_id, organization_id=owner.organization_id,
                              field_definition_id=definition_id, owner_type_code=owner_type, owner_id=owner.id,
                              **columns))
            counts["cf_set"] += 1
        elif any(getattr(row, c) != v for c, v in columns.items()):
            for column, column_value in columns.items():
                setattr(row, column, column_value)
            counts["cf_set"] += 1

    # Zoho omits empty fields: a Zoho-defined value not present any more is cleared.
    zoho_defined = set()
    if existing:
        zoho_defined = set((await db.scalars(select(FieldDefinition.id).where(
            FieldDefinition.id.in_(list(existing)), FieldDefinition.zoho_field_id.is_not(None)))).all())
    for definition_id, row in existing.items():
        if definition_id not in present and definition_id in zoho_defined:
            row.soft_delete(reason=REMOVED_REASON)
            counts["cf_cleared"] += 1
    await db.flush()
    return counts


__all__ = ["project_custom_fields"]
