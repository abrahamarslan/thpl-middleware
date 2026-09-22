"""Core master data: brands, manufacturers, their relations and aliases.

Hermetic tests assert the schema shape (generated columns, partial indexes,
closed vocabularies, request validation). Integration tests use the ``worlds``
fixture (two tenants with users) and the migrated scratch database; they skip
when it is absent.
"""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import Computed, text
from sqlalchemy.exc import IntegrityError

from app.database.db import Base
from app.database.tenancy import tenant_scope
from app.modules.brands import service as brand_service
from app.modules.brands.enums import BrandKind, values
from app.modules.brands.model import Brand, BrandManufacturer
from app.modules.brands.schema import BrandCreate
from app.modules.entities.model import EntityAlias
from app.modules.entities.scope import CoreRuleError
from app.modules.manufacturers.enums import ManufacturerIdentifierKind
from app.modules.manufacturers.model import Manufacturer, ManufacturerIdentifier
from app.modules.manufacturers.schema import ManufacturerIdentifierCreate


# ── hermetic: schema shape ──────────────────────────────────────────────────

def test_the_six_core_tables_live_in_the_core_schema():
    tables = {t.name for t in Base.metadata.tables.values() if t.schema == "core"}
    assert tables == {"entity_types", "brands", "manufacturers",
                      "brand_manufacturers", "manufacturer_identifiers", "entity_aliases"}


def test_normalized_columns_are_stored_generated_columns():
    for model, column in ((Brand, "name_normalized"), (Manufacturer, "name_normalized"),
                          (EntityAlias, "alias_normalized"), (ManufacturerIdentifier, "value_normalized")):
        computed = model.__table__.c[column].computed
        assert isinstance(computed, Computed) and computed.persisted is True, model.__name__


def test_uniqueness_on_soft_deletable_tables_is_partial():
    expected = {
        Brand: ("uq_brands_scope_name", "uq_brands_scope_code", "uq_brands_scope_slug"),
        Manufacturer: ("uq_manufacturers_scope_name", "uq_manufacturers_scope_code", "uq_manufacturers_scope_slug"),
        BrandManufacturer: ("uq_brand_manufacturers_current", "ux_brand_manufacturers_default"),
        ManufacturerIdentifier: ("uq_manufacturer_identifiers_current",),
        EntityAlias: ("uq_entity_aliases_current",),
    }
    for model, names in expected.items():
        indexes = {i.name: i for i in model.__table__.indexes}
        for name in names:
            where = indexes[name].dialect_options["postgresql"].get("where")
            assert where is not None, f"{model.__tablename__}.{name} must be partial"


def test_the_vocabularies_are_closed_sets():
    assert values(BrandKind) == "'own','third_party','private_label'"


def test_request_schemas_validate_the_obvious_mistakes():
    with pytest.raises(ValidationError):
        BrandCreate(name="Acme", country_code="IND")
    with pytest.raises(ValidationError):
        ManufacturerIdentifierCreate(kind=ManufacturerIdentifierKind.GSTIN, value="")


def test_search_registry_attributes_are_real_columns():
    """A typo in the Meili registry is an opaque production error; make it build-time."""
    from app.modules.search.registry import SEARCHABLE_ENTITIES

    for index in ("brands", "manufacturers"):
        entity = SEARCHABLE_ENTITIES[index]
        columns = set(entity.resolve_model().__table__.c.keys())
        declared = [*entity.searchable, *entity.filterable, *entity.sortable]
        assert declared, index
        for attr in declared:
            assert attr in columns, f"{index}.{attr} is not a column"


# ── integration: brands ─────────────────────────────────────────────────────

async def _create_brand(client, headers, name="Acme Pharma", **extra) -> dict:
    response = await client.post("/api/brands", json={"name": name, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_create_read_and_list_a_brand(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)

    data = await _create_brand(client, headers, code="AP", kind="own")
    assert data["slug"] == "acme-pharma"
    assert data["status"] == "active" and data["row_version"] == 1
    assert data["created_by_name"] == acme.member.name
    assert data["organization_id"]

    by_uuid = await client.get(f"/api/brands/{data['id']}", headers=headers)
    assert by_uuid.json()["data"]["name"] == "Acme Pharma"

    listed = await client.get("/api/brands", headers=headers)
    assert [b["name"] for b in listed.json()["data"]] == ["Acme Pharma"]
    assert (await client.get("/api/brands", params={"q": "acme"}, headers=headers)).json()["data"]


async def test_a_duplicate_name_is_a_conflict_and_slugs_dedupe(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    await _create_brand(client, headers, name="Acme Pharma")

    duplicate = await client.post("/api/brands", json={"name": "acme   pharma"}, headers=headers)
    assert duplicate.status_code == 409

    # A different name that slugifies to the same value gets a numeric suffix.
    other = await _create_brand(client, headers, name="Acme-Pharma")
    assert other["slug"] == "acme-pharma-2"


async def test_a_brand_cannot_be_its_own_ancestor(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    parent = await _create_brand(client, headers, name="Parent")
    child = await _create_brand(client, headers, name="Child", parent_id=parent["id"])

    move = await client.patch(f"/api/brands/{parent['id']}",
                              json={"parent_id": child["id"], "row_version": parent["row_version"]},
                              headers=headers)
    assert move.status_code == 422 and move.json()["code"] == "core_rule_violation"


async def test_a_stale_row_version_is_a_409(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    data = await _create_brand(client, headers)

    ok = await client.patch(f"/api/brands/{data['id']}",
                            json={"description": "updated", "row_version": data["row_version"]},
                            headers=headers)
    assert ok.status_code == 200 and ok.json()["data"]["row_version"] == 2

    stale = await client.patch(f"/api/brands/{data['id']}",
                               json={"description": "again", "row_version": data["row_version"]},
                               headers=headers)
    assert stale.status_code == 409 and stale.json()["data"]["current_row_version"] == 2


async def test_one_tenant_never_sees_anothers_brand(worlds, db):
    client, acme, globex = worlds
    data = await _create_brand(client, acme.auth(acme.member))

    assert (await client.get(f"/api/brands/{data['id']}",
                             headers=globex.auth(globex.member))).status_code == 404
    assert (await client.get("/api/brands", headers=globex.auth(globex.member))).json()["data"] == []


# ── integration: brand ↔ manufacturer ───────────────────────────────────────

async def _create_manufacturer(client, headers, name="Acme Mfg", **extra) -> dict:
    response = await client.post("/api/manufacturers", json={"name": name, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def test_link_a_manufacturer_and_refuse_a_duplicate_current_link(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    manufacturer = await _create_manufacturer(client, headers)

    link = await client.post(f"/api/brands/{brand['id']}/manufacturers",
                             json={"manufacturer_id": manufacturer["id"], "kind": "manufacturer"},
                             headers=headers)
    assert link.status_code == 201, link.text
    assert link.json()["data"]["kind"] == "manufacturer"

    duplicate = await client.post(f"/api/brands/{brand['id']}/manufacturers",
                                  json={"manufacturer_id": manufacturer["id"], "kind": "manufacturer"},
                                  headers=headers)
    assert duplicate.status_code == 409

    links = await client.get(f"/api/brands/{brand['id']}/manufacturers", headers=headers)
    assert len(links.json()["data"]) == 1


async def test_overlapping_validity_windows_are_refused(worlds, db):
    client, acme, _ = worlds
    org = acme.organization
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)
    manufacturer = await _create_manufacturer(client, headers)

    with tenant_scope(acme.tenant.id, organization_id=org.id):
        db.add(BrandManufacturer(brand_id=brand["id"], manufacturer_id=manufacturer["id"],
                                 valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 1)))
        await db.flush()
    with pytest.raises(IntegrityError, match="overlapping window"):
        with tenant_scope(acme.tenant.id, organization_id=org.id):
            db.add(BrandManufacturer(brand_id=brand["id"], manufacturer_id=manufacturer["id"],
                                     valid_from=date(2026, 3, 1), valid_to=date(2026, 9, 1)))
            await db.commit()
    await db.rollback()


# ── integration: identifiers ────────────────────────────────────────────────

async def test_statutory_identifier_formats_are_enforced(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    manufacturer = await _create_manufacturer(client, headers)

    bad = await client.post(f"/api/manufacturers/{manufacturer['id']}/identifiers",
                            json={"kind": "gstin", "value": "NOT-A-GSTIN"}, headers=headers)
    assert bad.status_code == 422 and bad.json()["code"] == "core_rule_violation"

    good = await client.post(f"/api/manufacturers/{manufacturer['id']}/identifiers",
                             json={"kind": "gstin", "value": "27AAPFU0939F1ZV"}, headers=headers)
    assert good.status_code == 201, good.text
    assert good.json()["data"]["value"] == "27AAPFU0939F1ZV"


# ── integration: aliases and the registry ───────────────────────────────────

async def test_the_entity_registry_is_seeded(worlds, db):
    client, acme, _ = worlds
    codes = {t["code"] for t in
             (await client.get("/api/entities/types", headers=acme.auth(acme.member))).json()["data"]}
    assert {"brand", "manufacturer"} <= codes


async def test_an_alias_round_trips(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.member)
    brand = await _create_brand(client, headers)

    created = await client.post("/api/entities/aliases",
                                json={"entity_type": "brand", "entity_id": brand["id"],
                                      "alias": "Acme", "kind": "abbreviation"}, headers=headers)
    assert created.status_code == 201, created.text

    listed = await client.get("/api/entities/aliases",
                              params={"entity_type": "brand", "entity_id": brand["id"]}, headers=headers)
    assert [a["alias"] for a in listed.json()["data"]] == ["Acme"]


async def test_an_alias_target_must_exist(worlds, db):
    client, acme, _ = worlds
    org = acme.organization
    with tenant_scope(acme.tenant.id, organization_id=org.id):
        db.add(EntityAlias(entity_type="brand", entity_id=999_999, alias="Ghost",
                           tenant_id=acme.tenant.id, organization_id=org.id))
        with pytest.raises(IntegrityError, match="does not exist"):
            await db.commit()
    await db.rollback()


async def test_create_brand_requires_an_organization(db):
    """A tenant with no organization gets a usable 422, not a raw IntegrityError
    from the NOT NULL organization_id.

    It takes a bare tenant to reach this: a migrated database always gives the
    DEFAULT tenant an organization, so `app/database/scope.py` resolves the
    deployment default for every ordinary caller.
    """
    from app.modules.tenants.model import Tenant

    bare = Tenant(tenant_code="BARE-BRAND", name="Bare Ltd",
                  primary_contact_email="ops@bare.example", status="active")
    db.add(bare)
    await db.flush()
    with tenant_scope(bare.id):
        with pytest.raises(CoreRuleError):
            await brand_service.create_brand(db, BrandCreate(name="No Org"))


# ── integration: the database guards exist ──────────────────────────────────

async def test_the_guard_functions_and_triggers_are_installed(db):
    functions = (await db.execute(text(
        "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'core'"
    ))).scalars().all()
    assert {"assert_entity_exists", "check_entity_alias", "find_orphan_entity_aliases",
            "guard_brand_parent", "check_brand_manufacturer_overlap"} <= set(functions)

    triggers = (await db.execute(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))).scalars().all()
    assert {"ctrg_entity_aliases_integrity", "trg_brands_parent_guard",
            "ctrg_brand_manufacturers_overlap"} <= set(triggers)
