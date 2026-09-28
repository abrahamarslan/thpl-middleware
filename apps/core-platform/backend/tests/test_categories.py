"""Categories & taxonomies — schema shape and end-to-end behaviour.

Hermetic tests assert the schema contract (generated column, partial
uniqueness, the ``metadata`` attribute trap). Integration tests use the
``worlds`` two-tenant fixture and the migrated scratch database; they skip when
the database is absent. The deferred-constraint tests assert the D13 envelope
(a clean 4xx, never an opaque 500) rather than a raw traceback.
"""

import pytest
from sqlalchemy import Computed, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.database.tenancy import tenant_scope
from app.modules.brands.model import Brand
from app.modules.categories.enums import CategoryRecordStatus
from app.modules.categories.model import Category, Categorizable, Taxonomy, TaxonomyEntityType


# ── hermetic: schema shape ──────────────────────────────────────────────────

def test_name_normalized_is_a_stored_generated_column():
    computed = Category.__table__.c["name_normalized"].computed
    assert isinstance(computed, Computed) and computed.persisted is True


def test_uniqueness_on_soft_deletable_tables_is_partial():
    expected = {
        Taxonomy: ("uq_taxonomies_scope_slug",),
        TaxonomyEntityType: ("uq_taxonomy_entity_types_scope",),
        Category: ("uq_categories_zoho_id_live", "uq_categories_scope_code",
                   "uq_categories_scope_slug"),
        Categorizable: ("uq_categorizables_category_thing", "uq_categorizables_one_primary"),
    }
    for model, names in expected.items():
        indexes = {i.name: i for i in model.__table__.indexes}
        for name in names:
            where = indexes[name].dialect_options["postgresql"].get("where")
            assert where is not None, f"{model.__tablename__}.{name} must be partial"


def test_the_metadata_attribute_trap_is_avoided():
    # DB column stays `metadata`; the Python attribute is `metadata_`.
    assert Category.__table__.c["metadata"].name == "metadata"
    assert hasattr(Category, "metadata_")
    assert Categorizable.__table__.c["metadata"].name == "metadata"
    assert hasattr(Categorizable, "metadata_")


def test_record_status_vocabulary_is_closed():
    assert set(CategoryRecordStatus) == {CategoryRecordStatus.DELETED,
                                         CategoryRecordStatus.NORMAL,
                                         CategoryRecordStatus.ARCHIVED}


def test_taxonomy_entity_types_uniqueness_cannot_be_a_fk_target():
    """The documented deviation: the whitelist unique is partial, so the
    database enforces the whitelist via the integrity trigger, not an FK."""
    from app.modules.categories.model import Categorizable as C

    fk_names = {fk.name for fk in C.__table__.foreign_keys}
    assert "fk_categorizables_entity_type" in fk_names
    assert "fk_categorizables_taxonomy_entity_type" not in fk_names


def test_search_registry_attributes_are_real_columns():
    from app.modules.search.registry import SEARCHABLE_ENTITIES

    entity = SEARCHABLE_ENTITIES["categories"]
    assert entity.index_name == Category.__tablename__
    columns = set(entity.resolve_model().__table__.c.keys())
    declared = [*entity.searchable, *entity.filterable, *entity.sortable]
    assert declared
    for attr in declared:
        assert attr in columns, f"categories.{attr} is not a column"


def test_categorizable_type_derivation():
    from app.modules.categories.mixins import categorizable_type_of

    class FleetPartner:
        pass

    class Widget:
        __categorizable_type__ = "brand"

    assert categorizable_type_of(FleetPartner) == "fleet_partner"
    assert categorizable_type_of(Widget) == "brand"


def test_a_crosswalk_entity_carries_no_in_place_mirror_columns():
    """``categories`` syncs through the crosswalk, whose gate state lives in
    sync.sync_records. The in-place mirror columns are never written on that
    path — a live sync left every one NULL/0 — so they must not exist."""
    columns = set(Category.__table__.c.keys())
    dead = {"zoho_raw", "zoho_raw_hash", "zoho_raw_synced_at", "zoho_last_modified_time", "synced_at",
            "sync_source", "sync_version", "remote_deleted_at", "custom_fields", "public_id",
            "sync_state", "pending_command_id", "last_pushed_at", "last_push_error"}
    assert not (columns & dead), sorted(columns & dead)
    assert "zoho_id" in columns          # the one echo a crosswalk entity keeps


def test_meta_keywords_is_a_json_array_end_to_end():
    from app.modules.categories.schema import CategoryCreate, CategoryOut

    assert CategoryCreate(taxonomy_id=1, name="x", meta_keywords=["a", "b"]).meta_keywords == ["a", "b"]
    assert CategoryOut.model_fields["meta_keywords"].annotation == (list[str] | None)


# ── integration helpers ─────────────────────────────────────────────────────

async def _taxonomy(client, headers, slug="grocery", name="Grocery") -> dict:
    response = await client.post("/api/taxonomies", json={"slug": slug, "name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _category(client, headers, taxonomy_id, name, **extra) -> dict:
    response = await client.post(
        "/api/categories", json={"taxonomy_id": taxonomy_id, "name": name, **extra}, headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _whitelist(client, headers, taxonomy_ref, *codes, allows_multiple=None):
    body = {"entity_types": [{"entity_type_code": code, "allows_multiple": allows_multiple}
                             for code in codes]}
    response = await client.put(f"/api/taxonomies/{taxonomy_ref}/entity-types", json=body, headers=headers)
    assert response.status_code == 200, response.text


async def _make_brand(db, acme, name="Acme Foods") -> Brand:
    with tenant_scope(acme.tenant.id, acme.organization.id):
        brand = Brand(name=name, organization_id=acme.organization.id,
                      owner_type="organization", owner_id=acme.organization.id)
        db.add(brand)
        await db.flush()
    return brand


# ── integration: taxonomy + tree ────────────────────────────────────────────

async def test_taxonomy_and_category_tree_roundtrip(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)

    tax = await _taxonomy(client, headers)
    root = await _category(client, headers, tax["id"], "Food")
    child = await _category(client, headers, tax["id"], "Snacks", parent_id=root["id"])

    response = await client.get(f"/api/categories/{root['id']}", headers=headers)
    root_detail = response.json()["data"]
    response = await client.get(f"/api/categories/{child['id']}", headers=headers)
    child_detail = response.json()["data"]

    assert root_detail["depth"] == 0 and root_detail["is_root"] is True
    assert child_detail["depth"] == 1
    assert root_detail["lft"] < child_detail["lft"] < child_detail["rgt"] < root_detail["rgt"]


async def test_moving_a_parent_under_its_child_is_rejected(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    parent = await _category(client, headers, tax["id"], "Food")
    child = await _category(client, headers, tax["id"], "Snacks", parent_id=parent["id"])

    # Creating a child recomputes the tree, bumping the parent's row_version;
    # a client must reload before moving (the optimistic-lock contract).
    parent = (await client.get(f"/api/categories/{parent['id']}", headers=headers)).json()["data"]
    response = await client.post(
        f"/api/categories/{parent['id']}/move",
        json={"parent_id": child["id"], "row_version": parent["row_version"]},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "core_rule_violation"


async def test_deleting_a_parent_with_live_children_conflicts(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    parent = await _category(client, headers, tax["id"], "Food")
    await _category(client, headers, tax["id"], "Snacks", parent_id=parent["id"])

    response = await client.delete(
        f"/api/categories/{parent['id']}?reason=cleanup", headers=headers,
    )
    assert response.status_code == 409, response.text


async def test_tenancy_isolation(worlds):
    client, acme, globex = worlds
    tax = await _taxonomy(client, acme.auth(acme.admin))

    listing = await client.get("/api/taxonomies", headers=globex.auth(globex.admin))
    assert listing.status_code == 200
    assert all(row["uuid"] != tax["uuid"] for row in listing.json()["data"])

    direct = await client.get(f"/api/taxonomies/{tax['uuid']}", headers=globex.auth(globex.admin))
    assert direct.status_code == 404


async def test_seo_keywords_round_trip_through_the_api(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    made = await _category(client, headers, tax["id"], "Soap", meta_keywords=["soap", "bodywash"],
                           meta_title="Soap")
    detail = (await client.get(f"/api/categories/{made['id']}", headers=headers)).json()["data"]
    assert detail["meta_keywords"] == ["soap", "bodywash"] and detail["meta_title"] == "Soap"


async def test_renaming_a_slug_recomputes_the_subtree_paths(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    root = await _category(client, headers, tax["id"], "Food", slug="food")
    child = await _category(client, headers, tax["id"], "Snacks", slug="snacks", parent_id=root["id"])
    root = (await client.get(f"/api/categories/{root['id']}", headers=headers)).json()["data"]

    response = await client.patch(f"/api/categories/{root['id']}",
                                  json={"slug": "eats", "row_version": root["row_version"]}, headers=headers)
    assert response.status_code == 200, response.text
    child = (await client.get(f"/api/categories/{child['id']}", headers=headers)).json()["data"]
    assert child["path"] == "/eats/snacks/"


async def test_is_root_follows_parent_id_even_for_a_raw_write(worlds, db):
    """The reconcile lane links a deferred parent with a bare UPDATE of parent_id.
    Without the BEFORE trigger that leaves is_root=true beside a parent and trips
    ck_categories_root_no_parent, aborting the whole drain."""
    from sqlalchemy import text

    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    root = await _category(client, headers, tax["id"], "Food")
    child = await _category(client, headers, tax["id"], "Snacks")            # a root, for now
    assert child["is_root"] is True

    await db.execute(text("UPDATE core.categories SET parent_id = :p WHERE id = :c"),
                     {"p": root["id"], "c": child["id"]})
    assert await db.scalar(text("SELECT is_root FROM core.categories WHERE id = :c"), {"c": child["id"]}) is False
    await db.execute(text("UPDATE core.categories SET parent_id = NULL WHERE id = :c"), {"c": child["id"]})
    assert await db.scalar(text("SELECT is_root FROM core.categories WHERE id = :c"), {"c": child["id"]}) is True


# ── integration: database-authoritative guards (deferred triggers) ──────────

async def test_missing_polymorphic_target_is_rejected_by_the_deferred_trigger(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    await _whitelist(client, headers, tax["uuid"], "brand")
    category = await _category(client, headers, tax["id"], "Food")

    # Service pre-flight passes (registered + whitelisted); the target does not
    # exist, so the DEFERRED trigger fires at COMMIT. The ``worlds`` fixture
    # yields the test session without committing, so the commit is explicit —
    # in production it happens inside get_db and the D13 handler maps it.
    response = await client.post(
        "/api/categorizables",
        json={"category_id": category["id"], "categorizable_type": "brand",
              "categorizable_id": 999_999_999},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    with pytest.raises(IntegrityError) as excinfo:
        await db.commit()
    assert excinfo.value.orig.sqlstate == "23503"


async def test_unregistered_entity_type_is_rejected_before_the_database(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    category = await _category(client, headers, tax["id"], "Food")

    response = await client.post(
        "/api/categorizables",
        json={"category_id": category["id"], "categorizable_type": "not_a_type",
              "categorizable_id": 1},
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "core_rule_violation"


async def test_single_valued_taxonomy_rejects_a_second_category(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    await _whitelist(client, headers, tax["uuid"], "brand", allows_multiple=False)
    first = await _category(client, headers, tax["id"], "Food")
    second = await _category(client, headers, tax["id"], "Beverages")
    brand = await _make_brand(db, acme)

    ok = await client.post(
        "/api/categorizables",
        json={"category_id": first["id"], "categorizable_type": "brand",
              "categorizable_id": brand.id},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    await db.commit()  # the first assignment is valid

    clash = await client.post(
        "/api/categorizables",
        json={"category_id": second["id"], "categorizable_type": "brand",
              "categorizable_id": brand.id},
        headers=headers,
    )
    assert clash.status_code == 201, clash.text
    with pytest.raises(IntegrityError) as excinfo:
        await db.commit()
    assert excinfo.value.orig.sqlstate == "23P01"


async def test_sync_replace_set_and_primary(worlds, db):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    await _whitelist(client, headers, tax["uuid"], "brand", allows_multiple=True)
    first = await _category(client, headers, tax["id"], "Food")
    second = await _category(client, headers, tax["id"], "Beverages")
    brand = await _make_brand(db, acme)

    body = {"categorizable_type": "brand", "categorizable_id": brand.id,
            "taxonomy_id": tax["id"],
            "items": [{"category_id": first["id"], "is_primary": True},
                      {"category_id": second["id"]}]}
    created = await client.post("/api/categorizables/sync", json=body, headers=headers)
    assert created.status_code == 200, created.text
    rows = created.json()["data"]
    assert len(rows) == 2
    primaries = [row for row in rows if row["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["category_id"] == first["id"]

    # Replace-set: only the second survives, and it becomes the single primary.
    body["items"] = [{"category_id": second["id"], "is_primary": True}]
    replaced = await client.post("/api/categorizables/sync", json=body, headers=headers)
    assert replaced.status_code == 200, replaced.text
    rows = replaced.json()["data"]
    assert len(rows) == 1 and rows[0]["category_id"] == second["id"] and rows[0]["is_primary"]


def test_deferred_constraint_errors_map_to_a_clean_envelope():
    """The D13 envelope contract: SQLSTATE → status, not an opaque 500."""
    from sqlalchemy.orm.exc import StaleDataError

    from app.common.exception.handlers import _SQLSTATE_MAP
    from app.main import app

    assert IntegrityError in app.exception_handlers
    assert StaleDataError in app.exception_handlers
    assert _SQLSTATE_MAP["23505"][0] == 409
    assert _SQLSTATE_MAP["23503"][0] == 422
    assert _SQLSTATE_MAP["23514"][0] == 422
    assert _SQLSTATE_MAP["23P01"][0] == 409


# ── integration: N+1 regression on the Fat detail read ──────────────────────

async def test_detail_read_query_count_is_constant(worlds):
    client, acme, _ = worlds
    headers = acme.auth(acme.admin)
    tax = await _taxonomy(client, headers)
    category = await _category(client, headers, tax["id"], "Food")
    await _category(client, headers, tax["id"], "Snacks", parent_id=category["id"])

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _capture)
    try:
        for _ in range(3):
            response = await client.get(f"/api/categories/{category['id']}", headers=headers)
            assert response.status_code == 200, response.text
    finally:
        event.remove(Engine, "before_cursor_execute", _capture)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    # Tags + documents are selectinloads (bounded), so the count does not grow
    # with repeated reads of the same row.
    assert len(selects) <= 24, len(selects)
