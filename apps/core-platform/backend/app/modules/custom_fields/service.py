"""Custom-fields business logic (service layer).

| Rule | Pre-flight (clean 422/409) | Database (authoritative) |
|---|---|---|
| owner type must be registered | ``_assert_owner_type_registered`` | FK → ``core.entity_types.code`` |
| owner instance must exist | ``_assert_owner_exists`` (calls the DB function) | deferred ``check_field_value_integrity`` → ``core.assert_entity_exists`` |
| a value's column matches its data type | ``coerce_value`` | deferred ``check_field_value_integrity`` |
| one live value per (field, owner) | upsert in ``set_value`` | ``uq_field_values_field_owner`` |
| at most one typed column populated | ``_value_columns`` | ``ck_field_values_single_value`` |
| api_name unique per owner type | ``find_definition_by_api_name`` | ``uq_field_definitions_scope_apiname`` |
| a dependency is a real field of the same owner type | ``_validate_dependency`` | ``fk_field_definitions_depends_on`` |
| changing a data type with live values is unsafe | ``_reject_data_type_change_with_values`` | — (trigger only fires on values) |
| values/definitions are organization-scoped | ``scope.require_organization_id`` | composite FKs |

The storage-column trigger fires at COMMIT, so a raw write that bypasses this
service is still rejected — applications must treat commit failure as the
validation signal. This service pre-flights the common cases for a clean error.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.database import scope
from app.modules.activity.recorder import record_activity
from app.modules.custom_fields import crud
from app.modules.custom_fields.enums import PiiType, StorageColumn
from app.modules.custom_fields.errors import CustomFieldRuleError
from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue
from app.modules.custom_fields.schema import (
    FieldDefinitionCreate,
    FieldDefinitionUpdate,
    FieldValueSet,
    FieldValueSync,
)

logger = structlog.get_logger("app.custom_fields")

_TRUE = {"true", "1", "yes", "y", "on"}
_FALSE = {"false", "0", "no", "n", "off", ""}


# ── pure helpers (hermetically unit-tested) ──────────────────────────────────

def _to_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                d = dt.date.fromisoformat(value)
            except ValueError as exc:
                raise CustomFieldRuleError(f"{value!r} is not a valid ISO date/datetime") from exc
            parsed = dt.datetime(d.year, d.month, d.day)
    else:
        raise CustomFieldRuleError(f"{value!r} is not a valid date/datetime")
    # timestamptz needs an aware value; an unspecified offset is treated as UTC.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in _FALSE:
            return False
    raise CustomFieldRuleError(f"{value!r} is not a valid boolean")


def coerce_value(storage_column: str, value: Any) -> Any:
    """Convert a client JSON scalar to the Python type the storage column holds.

    Raises ``CustomFieldRuleError`` for a value that cannot inhabit the column,
    so the caller gets a 422 instead of a commit-time trigger failure.
    """
    if value is None:
        return None
    if storage_column == StorageColumn.VALUE_TEXT:
        if isinstance(value, (dict, list)):
            raise CustomFieldRuleError("This field stores text; a structured value was sent")
        return str(value)
    if storage_column == StorageColumn.VALUE_NUMERIC:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CustomFieldRuleError(f"{value!r} is not a valid number") from exc
    if storage_column == StorageColumn.VALUE_DATE:
        return _to_datetime(value)
    if storage_column == StorageColumn.VALUE_BOOLEAN:
        return _to_bool(value)
    if storage_column == StorageColumn.VALUE_JSON:
        return value
    raise CustomFieldRuleError(f"Unknown storage column {storage_column!r}")


def value_columns(storage_column: str, value: Any) -> dict[str, Any]:
    """All five typed columns, with the value placed in the correct one."""
    columns: dict[str, Any] = {
        "value_text": None, "value_numeric": None, "value_date": None,
        "value_boolean": None, "value_json": None,
    }
    if value is not None:
        columns[storage_column] = coerce_value(storage_column, value)
    return columns


def _stringify(values: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in values.items()}


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


# ── integrity pre-flight ─────────────────────────────────────────────────────

async def _assert_owner_type_registered(db: AsyncSession, owner_type_code: str) -> None:
    found = (await db.execute(
        text("SELECT 1 FROM core.entity_types WHERE code = :code AND deleted_at IS NULL"),
        {"code": owner_type_code},
    )).first()
    if found is None:
        raise CustomFieldRuleError(
            f"'{owner_type_code}' is not a registered entity type",
            data={"hint": "GET /api/entities/types lists the registered codes"},
        )


async def _assert_owner_exists(db: AsyncSession, owner_type_code: str, owner_id: int) -> None:
    """Prove the polymorphic owner instance exists, using the DB function.

    A failure aborts the current statement; the caller raises immediately, so
    the session's rollback (``get_db``) discards the aborted transaction.
    """
    try:
        await db.execute(
            text("SELECT core.assert_entity_exists(:t, :i)"),
            {"t": owner_type_code, "i": owner_id},
        )
    except IntegrityError as exc:
        raise CustomFieldRuleError(
            f"{owner_type_code} {owner_id} does not exist (or its type is not registered)",
            data={"owner_type_code": owner_type_code, "owner_id": owner_id},
        ) from exc


async def _validate_dependency(
    db: AsyncSession, organization_id: int, owner_type_code: str, depends_on_field_id: int,
) -> None:
    parent = await crud.get_definition_by_id(db, depends_on_field_id, organization_id)
    if parent is None:
        raise NotFoundError(f"Depended-on field {depends_on_field_id} not found")
    if parent.owner_type_code != owner_type_code:
        raise CustomFieldRuleError("A field can only depend on another field of the same owner type")


# ── data types ───────────────────────────────────────────────────────────────

async def list_data_types(db: AsyncSession) -> list[DataType]:
    return await crud.list_data_types(db)


# ── field definitions ────────────────────────────────────────────────────────

async def _definition_data_type(
    db: AsyncSession, organization_id: int, definition: FieldDefinition,
) -> DataType:
    data_type = await crud.get_data_type_by_id(db, definition.data_type_id)
    if data_type is None:  # FK makes this impossible; kept for a typed read
        raise CustomFieldRuleError(f"Data type {definition.data_type_id} not found")
    return data_type


async def list_definitions(
    db: AsyncSession, *, owner_type_code: str | None = None, is_active: bool | None = None,
    page: int = 1, page_size: int = 100,
) -> list[FieldDefinition]:
    organization_id = await scope.require_organization_id(db)
    return await crud.list_definitions(
        db, organization_id, owner_type_code=owner_type_code, is_active=is_active,
        page=page, page_size=page_size,
    )


async def get_definition(db: AsyncSession, ref: str) -> FieldDefinition:
    organization_id = await scope.require_organization_id(db)
    definition = await crud.get_definition(db, ref, organization_id)
    if definition is None:
        raise NotFoundError(f"Custom field '{ref}' not found")
    return definition


async def create_definition(
    db: AsyncSession, body: FieldDefinitionCreate, *, actor_id: int | None = None,
) -> FieldDefinition:
    organization_id = await scope.require_organization_id(db)
    values = _stringify(body.model_dump(exclude_none=True))

    await _assert_owner_type_registered(db, body.owner_type_code)
    data_type = await crud.get_data_type_by_code(db, body.data_type_code)
    if data_type is None:
        raise CustomFieldRuleError(
            f"'{body.data_type_code}' is not a known data type",
            data={"hint": "GET /api/custom-fields/data-types lists the codes"},
        )
    if await crud.find_definition_by_api_name(
        db, organization_id, body.owner_type_code, body.api_name,
    ) is not None:
        raise ConflictError(
            f"A field with api_name '{body.api_name}' already exists for owner type "
            f"'{body.owner_type_code}' in this organization"
        )
    if body.depends_on_field_id is not None:
        await _validate_dependency(
            db, organization_id, body.owner_type_code, body.depends_on_field_id,
        )

    values.pop("data_type_code", None)
    values["data_type_id"] = data_type.id
    values["organization_id"] = organization_id

    definition = await crud.create_definition(db, values)
    await record_activity(
        db, action="custom_field_definition_created", actor_id=actor_id,
        subject_type="FieldDefinition", subject_id=str(definition.uuid),
        changes={"after": {"owner_type_code": definition.owner_type_code,
                           "api_name": definition.api_name, "data_type": data_type.code}},
    )
    logger.info("custom_field.definition.created", definition_id=definition.id,
                owner_type_code=definition.owner_type_code, api_name=definition.api_name)
    return await crud.get_definition(db, str(definition.uuid), organization_id) or definition


async def update_definition(
    db: AsyncSession, ref: str, body: FieldDefinitionUpdate, *, actor_id: int | None = None,
) -> FieldDefinition:
    organization_id = await scope.require_organization_id(db)
    definition = await crud.get_definition(db, ref, organization_id)
    if definition is None:
        raise NotFoundError(f"Custom field '{ref}' not found")
    _check_version(definition, body.row_version, f"Custom field '{definition.api_name}'")

    changes = _stringify(body.model_dump(exclude_unset=True, exclude={"row_version"}))

    if "data_type_code" in changes:
        code = changes.pop("data_type_code")
        data_type = await crud.get_data_type_by_code(db, code)
        if data_type is None:
            raise CustomFieldRuleError(f"'{code}' is not a known data type")
        if data_type.id != definition.data_type_id:
            # The trigger does not re-check existing rows on a definition update.
            if await crud.list_live_values_for_definition(db, organization_id, definition.id):
                raise CustomFieldRuleError(
                    "This field already has values; changing its data type would invalidate them. "
                    "Migrate or clear the values first."
                )
            changes["data_type_id"] = data_type.id

    if changes.get("depends_on_field_id") is not None:
        await _validate_dependency(
            db, organization_id, definition.owner_type_code, changes["depends_on_field_id"],
        )

    for field, value in changes.items():
        setattr(definition, field, value)
    await db.flush()
    await record_activity(
        db, action="custom_field_definition_updated", actor_id=actor_id,
        subject_type="FieldDefinition", subject_id=str(definition.uuid),
        changes={"after": {k: str(v) for k, v in changes.items()}},
    )
    return await crud.get_definition(db, str(definition.uuid), organization_id) or definition


async def delete_definition(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    """Soft-delete the definition and every live value under it (never a hard DELETE)."""
    organization_id = await scope.require_organization_id(db)
    definition = await crud.get_definition(db, ref, organization_id)
    if definition is None:
        raise NotFoundError(f"Custom field '{ref}' not found")
    for value in await crud.list_live_values_for_definition(db, organization_id, definition.id):
        value.soft_delete(reason=f"field definition {definition.uuid} deleted: {reason}", by=actor_id)
    definition.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="custom_field_definition_deleted", actor_id=actor_id,
        subject_type="FieldDefinition", subject_id=str(definition.uuid), context={"reason": reason},
    )
    logger.info("custom_field.definition.deleted", definition_id=definition.id)


# ── field values ─────────────────────────────────────────────────────────────

async def list_values_for_owner(
    db: AsyncSession, owner_type_code: str, owner_id: int,
) -> list[FieldValue]:
    organization_id = await scope.require_organization_id(db)
    return await crud.list_values_for_owner(db, organization_id, owner_type_code, owner_id)


async def _prepare_value(
    db: AsyncSession, organization_id: int, definition_id: int, owner_type_code: str, owner_id: int,
) -> tuple[FieldDefinition, DataType]:
    definition = await crud.get_definition_by_id(db, definition_id, organization_id)
    if definition is None:
        raise NotFoundError(f"Custom field definition {definition_id} not found")
    if definition.owner_type_code != owner_type_code:
        raise CustomFieldRuleError(
            f"Field {definition_id} is defined for '{definition.owner_type_code}', "
            f"not '{owner_type_code}'"
        )
    if definition.is_active is False:
        raise CustomFieldRuleError(f"Field '{definition.api_name}' is inactive")
    return definition, await _definition_data_type(db, organization_id, definition)


async def set_value(
    db: AsyncSession, body: FieldValueSet, *, actor_id: int | None = None,
) -> FieldValue:
    organization_id = await scope.require_organization_id(db)
    await _assert_owner_exists(db, body.owner_type_code, body.owner_id)
    definition, data_type = await _prepare_value(
        db, organization_id, body.field_definition_id, body.owner_type_code, body.owner_id,
    )
    columns = value_columns(data_type.storage_column, body.value)

    value = await crud.find_value(db, organization_id, definition.id, body.owner_id)
    if value is None:
        value = await crud.create_value(db, {
            "organization_id": organization_id,
            "field_definition_id": definition.id,
            "owner_type_code": definition.owner_type_code,
            "owner_id": body.owner_id,
            **columns,
        })
    else:
        for column, column_value in columns.items():
            setattr(value, column, column_value)
        await db.flush()

    await record_activity(
        db, action="custom_field_value_set", actor_id=actor_id,
        subject_type=body.owner_type_code, subject_id=body.owner_id,
        changes={"after": {"field_definition_id": definition.id, "api_name": definition.api_name,
                           "cleared": body.value is None}},
    )
    logger.info("custom_field.value.set", definition_id=definition.id,
                owner_type_code=body.owner_type_code, owner_id=body.owner_id)
    fetched = await crud.get_value(db, str(value.uuid), organization_id)
    return fetched or value


async def sync_values(
    db: AsyncSession, body: FieldValueSync, *, actor_id: int | None = None,
) -> list[FieldValue]:
    """Replace an owner's whole value set for the fields named (tags-sync shape).

    Named definitions are upserted; existing live values for the owner that are
    not named are soft-deleted, so the call is idempotent.
    """
    organization_id = await scope.require_organization_id(db)
    await _assert_owner_exists(db, body.owner_type_code, body.owner_id)

    existing = {
        v.field_definition_id: v
        for v in await crud.list_values_for_owner(db, organization_id, body.owner_type_code, body.owner_id)
    }
    requested: set[int] = set()
    for item in body.values:
        definition, data_type = await _prepare_value(
            db, organization_id, item.field_definition_id, body.owner_type_code, body.owner_id,
        )
        requested.add(definition.id)
        columns = value_columns(data_type.storage_column, item.value)
        value = existing.get(definition.id)
        if value is None:
            await crud.create_value(db, {
                "organization_id": organization_id,
                "field_definition_id": definition.id,
                "owner_type_code": definition.owner_type_code,
                "owner_id": body.owner_id,
                **columns,
            })
        else:
            for column, column_value in columns.items():
                setattr(value, column, column_value)

    for definition_id, value in existing.items():
        if definition_id not in requested:
            value.soft_delete(reason="field value not present in sync request", by=actor_id)

    await db.flush()
    await record_activity(
        db, action="custom_field_values_synced", actor_id=actor_id,
        subject_type=body.owner_type_code, subject_id=body.owner_id,
        changes={"synced_field_definition_ids": sorted(requested)},
    )
    logger.info("custom_field.values.synced", owner_type_code=body.owner_type_code,
                owner_id=body.owner_id, count=len(requested))
    return await crud.list_values_for_owner(db, organization_id, body.owner_type_code, body.owner_id)


async def delete_value(
    db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None,
) -> None:
    organization_id = await scope.require_organization_id(db)
    value = await crud.get_value(db, ref, organization_id)
    if value is None:
        raise NotFoundError(f"Custom field value '{ref}' not found")
    value.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="custom_field_value_deleted", actor_id=actor_id,
        subject_type=value.owner_type_code, subject_id=value.owner_id,
        context={"reason": reason},
    )


async def erase_pii_values_for_owner(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, reason: str, actor_id: int | None = None,
) -> int:
    """DPDP erasure: blank and soft-delete every value under a PII-classified field.

    The row is kept (audit of *that* an erasure happened) but its payload columns
    are nulled, so the personal data is gone. Non-PII values are untouched.
    Returns how many values were erased.
    """
    organization_id = await scope.require_organization_id(db)
    pii_fields = {
        d.id
        for d in await crud.list_definitions(db, organization_id, page=1, page_size=10_000)
        if d.pii_type in (PiiType.PII.value, PiiType.SENSITIVE_PII.value)
    }
    erased = 0
    for value in await crud.list_values_for_owner(
        db, organization_id, owner_type_code, owner_id,
    ):
        if value.field_definition_id not in pii_fields:
            continue
        value.value_text = None
        value.value_numeric = None
        value.value_date = None
        value.value_boolean = None
        value.value_json = None
        value.soft_delete(reason=f"DPDP erasure: {reason}", by=actor_id)
        erased += 1
    if erased:
        await db.flush()
        await record_activity(
            db, action="custom_field_pii_erased", actor_id=actor_id,
            subject_type=owner_type_code, subject_id=owner_id,
            changes={"erased_values": erased}, context={"reason": reason},
        )
        logger.info("custom_field.pii.erased", owner_type_code=owner_type_code,
                    owner_id=owner_id, erased=erased)
    return erased


__all__ = [
    "coerce_value",
    "value_columns",
    "list_data_types",
    "list_definitions",
    "get_definition",
    "create_definition",
    "update_definition",
    "delete_definition",
    "list_values_for_owner",
    "set_value",
    "sync_values",
    "delete_value",
    "erase_pii_values_for_owner",
]