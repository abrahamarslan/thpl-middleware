"""Catalogue phase 1 — masters (units, UQC, packaging types, sales channels, item groups, attributes).

Hermetic: vocabulary and schema rules. Integration (scratch Postgres + Redis via ``worlds``): the standard
units every organization is given, the API's rules (codes, classes, UQC, row_version, Zoho-owned fields,
in-use deletes, tree cycles), organization isolation and permissions.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.modules.catalogue.enums import UnitClass
from app.modules.catalogue.model import Unit
from app.modules.catalogue.schema.masters import AttributeCreate, PackagingTypeCreate, UnitCreate

# ── hermetic ─────────────────────────────────────────────────────────────────


def test_only_physical_classes_have_a_size():
    assert {c for c in UnitClass if c.is_physical} == {
        UnitClass.MASS, UnitClass.VOLUME, UnitClass.LENGTH, UnitClass.AREA, UnitClass.TIME}


def test_payloads_validate_codes_and_quantities():
    with pytest.raises(ValidationError):
        PackagingTypeCreate(code="shipper case", name="x")          # space not allowed
    with pytest.raises(ValidationError):
        UnitCreate(code="kg", name="Kilo", unit_class="mass", si_factor="0")   # must be > 0
    assert AttributeCreate(code="Volume", name="Volume").input_type.value == "select"


# ── integration helpers ──────────────────────────────────────────────────────


def _data(response, status=200):
    assert response.status_code == status, response.text
    return response.json()["data"]


# ── standard units ───────────────────────────────────────────────────────────


async def test_every_new_organization_gets_the_standard_units(worlds, db):
    _, acme, globex = worlds
    for world in (acme, globex):
        with tenant_scope(world.tenant.id, world.organization.id):
            codes = set((await db.scalars(
                select(Unit.code).where(Unit.organization_id == world.organization.id))).all())
        assert {"pcs", "btl", "box", "ctn", "g", "kg", "ml", "l", "cm", "in"} <= codes
    with tenant_scope(acme.tenant.id, acme.organization.id):
        kg = await db.scalar(select(Unit).where(Unit.organization_id == acme.organization.id, Unit.code == "kg"))
    assert kg.unit_class == "mass" and kg.si_factor == 1000 and kg.uqc_code == "KGS" and kg.is_system


async def test_uqc_codes_are_listed(worlds):
    client, acme, _ = worlds
    codes = {u["code"] for u in _data(await client.get("/api/catalogue/uqc-codes", headers=acme.auth(acme.admin)))}
    assert {"PCS", "BTL", "BOX", "CTN", "KGS", "MLT", "LTR", "TBS", "OTH"} <= codes


# ── units ────────────────────────────────────────────────────────────────────


async def test_unit_rules(worlds):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)

    strip = _data(await client.post("/api/catalogue/units", headers=h,
                                    json={"code": "Strip10", "name": "Strip of 10", "unit_class": "count",
                                          "uqc_code": "pac"}), 201)
    assert strip["uqc_code"] == "PAC" and strip["si_factor"] is None

    # a count unit has no physical size
    r = await client.post("/api/catalogue/units", headers=h,
                          json={"code": "case", "name": "Case", "unit_class": "count", "si_factor": "12"})
    assert r.status_code == 422 and r.json()["code"] == "catalogue_rule_violation"
    # codes are unique case-insensitively
    r = await client.post("/api/catalogue/units", headers=h, json={"code": "STRIP10", "name": "x", "unit_class": "count"})
    assert r.status_code == 409
    # the UQC must be a real GST code
    r = await client.post("/api/catalogue/units", headers=h, json={"code": "zz", "name": "x", "unit_class": "count",
                                                                    "uqc_code": "ZZZ"})
    assert r.status_code == 422

    mg = _data(await client.post("/api/catalogue/units", headers=h,
                                 json={"code": "mcg", "name": "Microgram", "unit_class": "mass", "si_factor": "0.000001",
                                       "decimal_places": 3}), 201)
    assert mg["unit_class"] == "mass"

    # optimistic lock
    r = await client.patch(f"/api/catalogue/units/{strip['uuid']}", headers=h, json={"name": "Strip", "row_version": 99})
    assert r.status_code == 409
    updated = _data(await client.patch(f"/api/catalogue/units/{strip['uuid']}", headers=h,
                                       json={"name": "Strip (10)", "row_version": strip["row_version"]}))
    assert updated["name"] == "Strip (10)" and updated["row_version"] == strip["row_version"] + 1

    masses = _data(await client.get("/api/catalogue/units?unit_class=mass", headers=h))
    assert {u["code"] for u in masses["items"]} >= {"g", "kg", "mcg"} and masses["total"] == len(masses["items"])

    # standard units are deactivated, never deleted; custom ones can go
    kg = next(u for u in masses["items"] if u["code"] == "kg")
    r = await client.delete(f"/api/catalogue/units/{kg['uuid']}?reason=cleanup", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "catalogue_in_use"
    _data(await client.delete(f"/api/catalogue/units/{mg['uuid']}?reason=not used", headers=h))
    assert (await client.get(f"/api/catalogue/units/{mg['uuid']}", headers=h)).status_code == 404


async def test_a_zoho_linked_unit_keeps_its_zoho_fields_read_only(worlds, db):
    client, acme, _ = worlds
    with tenant_scope(acme.tenant.id, acme.organization.id):
        unit = await db.scalar(select(Unit).where(Unit.organization_id == acme.organization.id, Unit.code == "box"))
        unit.zoho_id = "954919000000014124"
        await db.commit()
        version = unit.row_version
    h = acme.auth(acme.admin)
    r = await client.patch(f"/api/catalogue/units/{unit.uuid}", headers=h, json={"name": "Boxes", "row_version": version})
    assert r.status_code == 409 and r.json()["code"] == "zoho_owned_field"
    # a field Zoho does not feed stays editable
    ok = _data(await client.patch(f"/api/catalogue/units/{unit.uuid}", headers=h,
                                  json={"plural_name": "Boxes", "row_version": version}))
    assert ok["plural_name"] == "Boxes"


# ── packaging types & sales channels ─────────────────────────────────────────


async def test_packaging_types_check_their_units(worlds):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    units = {u["code"]: u for u in _data(await client.get("/api/catalogue/units?page_size=200", headers=h))["items"]}

    r = await client.post("/api/catalogue/packaging-types", headers=h,
                          json={"code": "SHIPPER_CASE", "name": "CFB shipper", "weight_unit_id": units["cm"]["id"]})
    assert r.status_code == 422 and "mass" in r.json()["msg"]

    case = _data(await client.post("/api/catalogue/packaging-types", headers=h, json={
        "code": "shipper_case", "name": "CFB master shipper", "is_container": True, "is_stackable": True,
        "stack_limit": 6, "standard_weight": "10.5", "weight_unit_id": units["kg"]["id"],
        "standard_length": "48", "dimension_unit_id": units["cm"]["id"], "properties": {"flute": "5-ply"},
    }), 201)
    assert case["code"] == "SHIPPER_CASE" and case["properties"] == {"flute": "5-ply"}
    assert (await client.post("/api/catalogue/packaging-types", headers=h,
                              json={"code": "SHIPPER_CASE", "name": "dup"})).status_code == 409
    r = await client.patch(f"/api/catalogue/packaging-types/{case['uuid']}", headers=h,
                           json={"valid_from": "2026-01-01", "valid_to": "2025-01-01", "row_version": case["row_version"]})
    assert r.status_code == 422


async def test_sales_channels_map_zoho_codes_once(worlds):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    gt = _data(await client.post("/api/catalogue/sales-channels", headers=h, json={
        "code": "STOREFRONT", "name": "General trade", "channel_kind": "general_trade", "zoho_code": "direct_sales"}), 201)
    r = await client.post("/api/catalogue/sales-channels", headers=h,
                          json={"code": "DISTRIBUTOR", "name": "Distributor", "zoho_code": "direct_sales"})
    assert r.status_code == 409
    page = _data(await client.get("/api/catalogue/sales-channels?channel_kind=general_trade", headers=h))
    assert [c["code"] for c in page["items"]] == [gt["code"]]


# ── item groups ──────────────────────────────────────────────────────────────


async def test_item_groups_form_a_tree_without_cycles(worlds):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    personal = _data(await client.post("/api/catalogue/item-groups", headers=h,
                                       json={"code": "personal_care", "name": "Personal care"}), 201)
    oral = _data(await client.post("/api/catalogue/item-groups", headers=h,
                                   json={"code": "ORAL_CARE", "name": "Oral care", "parent_id": personal["id"],
                                         "display_order": 4}), 201)
    tree = _data(await client.get("/api/catalogue/item-groups?tree=true", headers=h))
    assert tree[0]["code"] == "PERSONAL_CARE" and tree[0]["children"][0]["code"] == "ORAL_CARE"

    r = await client.patch(f"/api/catalogue/item-groups/{personal['uuid']}", headers=h,
                           json={"parent_id": oral["id"], "row_version": personal["row_version"]})
    assert r.status_code == 422 and "cycle" in r.json()["msg"]
    r = await client.delete(f"/api/catalogue/item-groups/{personal['uuid']}?reason=reorganise", headers=h)
    assert r.status_code == 409


# ── attributes ───────────────────────────────────────────────────────────────


async def test_attributes_carry_unique_options(worlds):
    client, acme, _ = worlds
    h = acme.auth(acme.admin)
    ml = next(u for u in _data(await client.get("/api/catalogue/units?q=ml", headers=h))["items"] if u["code"] == "ml")
    volume = _data(await client.post("/api/catalogue/attributes", headers=h, json={
        "code": "Volume", "name": "Volume", "input_type": "number", "unit_id": ml["id"],
        "options": [{"value": "50 ml", "numeric_value": "50"}, {"value": "95 ml", "numeric_value": "95", "position": 1}],
    }), 201)
    assert volume["code"] == "volume" and [o["value"] for o in volume["options"]] == ["50 ml", "95 ml"]

    r = await client.post(f"/api/catalogue/attributes/{volume['uuid']}/options", headers=h, json={"value": " 95 ML "})
    assert r.status_code == 409
    opt = _data(await client.post(f"/api/catalogue/attributes/{volume['uuid']}/options", headers=h,
                                  json={"value": "200 ml", "numeric_value": "200", "position": 2}), 201)
    renamed = _data(await client.patch(f"/api/catalogue/attributes/{volume['uuid']}/options/{opt['uuid']}", headers=h,
                                       json={"value": "200 mL", "row_version": opt["row_version"]}))
    assert renamed["value"] == "200 mL"
    _data(await client.delete(f"/api/catalogue/attributes/{volume['uuid']}/options/{opt['uuid']}?reason=wrong",
                              headers=h))
    detail = _data(await client.get(f"/api/catalogue/attributes/{volume['uuid']}", headers=h))
    assert [o["value"] for o in detail["options"]] == ["50 ml", "95 ml"]


# ── isolation & permissions ──────────────────────────────────────────────────


async def test_masters_are_organization_scoped_and_writes_need_permission(worlds):
    client, acme, globex = worlds
    group = _data(await client.post("/api/catalogue/item-groups", headers=acme.auth(acme.admin),
                                    json={"code": "MENS_GROOMING", "name": "Men's grooming"}), 201)

    assert (await client.get(f"/api/catalogue/item-groups/{group['uuid']}", headers=globex.auth(globex.admin))).status_code == 404
    assert _data(await client.get("/api/catalogue/item-groups", headers=globex.auth(globex.admin)))["total"] == 0

    # a member reads but cannot write
    assert _data(await client.get("/api/catalogue/item-groups", headers=acme.auth(acme.member)))["total"] == 1
    r = await client.post("/api/catalogue/item-groups", headers=acme.auth(acme.member), json={"code": "X", "name": "X"})
    assert r.status_code == 403
