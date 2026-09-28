"""Custom fields — the ``extfields`` engine.

Hermetic tests pin the schema shape and the pure coercion helpers; integration
tests drive the API against the migrated scratch database (they skip when it is
absent) using the shared ``worlds`` fixture.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database.db import Base
from app.database.tenancy import tenant_scope
from app.modules.custom_fields.errors import CustomFieldRuleError
from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue
from app.modules.custom_fields.service import coerce_value, value_columns


# ── hermetic: schema shape ──────────────────────────────────────────────────

def test_the_three_extfields_tables_live_in_the_extfields_schema():
    tables = {t.name for t in Base.metadata.tables.values() if t.schema == "extfields"}
    assert tables == {"data_types", "field_definitions", "field_values"}


def test_the_storage_column_set_is_closed():
    checks = {c.name: str(c.sqltext) for c in DataType.__table__.constraints if c.name}
    assert "value_text" in checks["ck_data_types_storage_column"]
    assert "value_json" in checks["ck_data_types_storage_column"]


def test_at_most_one_typed_column_is_populated():
    checks = {c.name for c in FieldValue.__table__.constraints}
    assert "ck_field_values_single_value" in checks


def test_uniqueness_on_the_soft_deletable_tables_is_partial():
    expected = {
        FieldDefinition: ("uq_field_definitions_scope_apiname",),
        FieldValue: ("uq_field_values_field_owner",),
        DataType: ("uq_data_types_code",),
    }
    for model, names in expected.items():
        indexes = {i.name: i for i in model.__table__.indexes}
        for name in names:
            where = indexes[name].dialect_options["postgresql"].get("where")
            assert where is not None, f"{model.__tablename__}.{name} must be partial"


def test_the_owner_type_is_a_fk_to_the_shared_registry():
    fks = {fk.name for fk in FieldValue.__table__.foreign_key_constraints}
    assert "fk_field_values_owner_type" in fks
    target = {fk.name: [e.target_fullname for e in fk.elements] for fk in FieldValue.__table__.foreign_key_constraints}
    assert target["fk_field_values_owner_type"] == ["core.entity_types.code"]


# ── hermetic: coercion ──────────────────────────────────────────────────────

def test_numeric_text_is_a_decimal_not_a_float():
    assert coerce_value("value_numeric", "45.50") == Decimal("45.50")


def test_boolean_accepts_the_common_serialisations():
    assert coerce_value("value_boolean", "false") is False
    assert coerce_value("value_boolean", "yes") is True


def test_dates_are_made_timezone_aware():
    assert coerce_value("value_date", "2026-01-02") == dt.datetime(2026, 1, 2, tzinfo=dt.UTC)


def test_text_rejects_a_structured_value():
    with pytest.raises(CustomFieldRuleError):
        coerce_value("value_text", {"a": 1})


def test_value_columns_places_the_value_in_exactly_one_column():
    columns = value_columns("value_json", [1, 2, 3])
    assert columns["value_json"] == [1, 2, 3]
    assert all(v is None for k, v in columns.items() if k != "value_json")


def test_a_null_value_populates_no_column():
    assert set(value_columns("value_numeric", None).values()) == {None}


# ── integration ─────────────────────────────────────────────────────────────

async def _create_brand(client, headers, name="Acme Pharma") -> dict:
    response = await client.post("/api/brands", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _create_definition(client, headers, **extra) -> dict:
    body = {"owner_type_code": "brand", "data_type_code": "text",
            "api_name": "warranty_terms", "label": "Warranty Terms", **extra}
    response = await client.post("/api/custom-fields/definitions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_the_data_type_lookup_is_seeded(worlds, db):
    client, acme, _ = worlds
    codes = {t["code"] for t in
             (await client.get("/api/custom-fields/data-types", headers=acme.auth(acme.member))).json()["data"]}
    assert {"amount", "text", "date", "checkbox", "multiselect"} <= codes


async def test_define_set_and_read_a_value(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    definition = await _create_definition(client, headers, api_name="country_of_origin",
                                          label="Country of Origin")

    saved = await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": brand["id"], "value": "India",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["value"] == "India"

    listed = await client.get("/api/custom-fields/values", headers=headers,
                              params={"owner_type_code": "brand", "owner_id": brand["id"]})
    assert [v["value"] for v in listed.json()["data"]] == ["India"]

    # Idempotent: setting again updates the same row (one value per field+owner).
    again = await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": brand["id"], "value": "Nepal",
    })
    assert again.status_code == 200
    listed = await client.get("/api/custom-fields/values", headers=headers,
                              params={"owner_type_code": "brand", "owner_id": brand["id"]})
    assert [v["value"] for v in listed.json()["data"]] == ["Nepal"]


async def test_a_numeric_field_stores_a_decimal_in_value_numeric(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    definition = await _create_definition(client, headers, data_type_code="amount",
                                          api_name="warranty_months", label="Warranty Months")

    saved = await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": brand["id"], "value": "24",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["value_numeric"] is not None
    assert saved.json()["data"]["value_text"] is None


async def test_a_duplicate_api_name_for_the_same_owner_type_is_a_409(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    await _create_definition(client, headers, api_name="dup")
    again = await client.post("/api/custom-fields/definitions", headers=headers, json={
        "owner_type_code": "brand", "data_type_code": "text", "api_name": "dup", "label": "Dup",
    })
    assert again.status_code == 409


async def test_an_unregistered_owner_type_is_a_422(worlds, db):
    client, acme, _ = worlds
    response = await client.post("/api/custom-fields/definitions", headers=acme.auth(acme.member), json={
        "owner_type_code": "spaceship", "data_type_code": "text", "api_name": "x", "label": "X",
    })
    assert response.status_code == 422 and response.json()["code"] == "custom_field_rule_violation"


async def test_a_value_for_a_missing_owner_is_a_422(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    definition = await _create_definition(client, headers)
    response = await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": 999_999, "value": "ghost",
    })
    assert response.status_code == 422 and response.json()["code"] == "custom_field_rule_violation"


async def test_one_tenant_never_sees_anothers_field(worlds, db):
    client, acme, globex = worlds
    definition = await _create_definition(client, acme.auth(acme.member))
    assert (await client.get(f"/api/custom-fields/definitions/{definition['id']}",
                             headers=globex.auth(globex.member))).status_code == 404


async def test_the_storage_column_trigger_refuses_a_wrong_file_at_commit(worlds, db):
    client, acme, _ = worlds
    org = acme.organization
    definition = await _create_definition(client, acme.auth(acme.member), data_type_code="amount",
                                          api_name="amount_field", label="Amount")
    brand = await _create_brand(client, acme.auth(acme.member))

    with tenant_scope(acme.tenant.id, organization_id=org.id):
        db.add(FieldValue(tenant_id=acme.tenant.id, organization_id=org.id,
                          field_definition_id=definition["id"], owner_type_code="brand",
                          owner_id=brand["id"], value_text="not a number"))
        with pytest.raises(IntegrityError):
            await db.commit()
    await db.rollback()


async def test_changing_a_data_type_with_values_is_refused(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    definition = await _create_definition(client, headers, data_type_code="text")
    await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": brand["id"], "value": "x",
    })
    changed = await client.patch(f"/api/custom-fields/definitions/{definition['id']}",
                                 headers=headers,
                                 json={"data_type_code": "number", "row_version": definition["row_version"]})
    assert changed.status_code == 422


async def test_pii_erasure_blanks_and_removes_values(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    definition = await _create_definition(client, headers, pii_type="sensitive_pii",
                                          api_name="tax_id", label="Tax ID")
    await client.post("/api/custom-fields/values", headers=headers, json={
        "field_definition_id": definition["id"], "owner_type_code": "brand",
        "owner_id": brand["id"], "value": "ABCDE1234F",
    })

    erased = await client.post("/api/custom-fields/values/erase-pii", headers=acme.auth(acme.admin),
                               params={"owner_type_code": "brand", "owner_id": brand["id"],
                                       "reason": "data principal request"})
    assert erased.status_code == 200 and erased.json()["data"]["erased_values"] == 1

    remaining = await client.get("/api/custom-fields/values", headers=headers,
                                 params={"owner_type_code": "brand", "owner_id": brand["id"]})
    assert remaining.json()["data"] == []


async def test_the_integrity_function_and_detector_are_installed(db):
    functions = (await db.execute(text(
        "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'extfields'"
    ))).scalars().all()
    assert {"check_field_value_integrity", "find_orphan_field_values"} <= set(functions)

    triggers = (await db.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))).scalars().all()
    assert "ctrg_field_values_integrity" in set(triggers)