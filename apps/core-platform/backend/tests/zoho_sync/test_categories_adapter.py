"""Zoho Books category adapter — mapper, engine and tree-integration tests.

Minimum coverage for a sync module (testing doctrine): mapper field
extraction, identity matching / no duplicates on re-sync, provenance, and the
module-specific behaviour this adapter adds — parent linking through the
crosswalk, the queue for a parent that cannot be linked yet, and nested-set
recompute. Zoho is always ``FakeZohoClient``; the same adapter runs through the
REAL transport in ``tests/zoho_core/test_masters_e2e.py``.
"""

from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.database.tenancy import tenant_scope
from app.modules.categories import service
from app.modules.categories.model import Category, Taxonomy
from app.modules.categories.schema import CategoryMove, CategoryOut, CategoryUpdate
from app.modules.categories.zoho import hooks
from app.modules.categories.zoho.fields import FIELDS
from app.modules.categories.zoho.spec import (
    CATEGORIES_CONFIG,
    CATEGORIES_TRANSLATOR,
    ZOHO_OWNED_CATEGORY_FIELDS,
)
from app.modules.organizations.model import Organization
from app.modules.sync.crosswalk import upsert_record
from app.modules.sync.models import LinkState, PendingReference, SyncRecord
from app.modules.sync.reconcile import drain_pending_references
from app.modules.sync.translation import CODECS, TranslationError, WriteIntent
from app.modules.taxes import assignment_crud as tax_crud
from app.modules.taxes.component import TaxComponent
from app.modules.tenants.model import Tenant
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.registry import sync_registry
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

MODULE = "categories"

ROOT = {
    "category_id": "4815000000044001",
    "name": "Electronics",
    "url": "electronics",
    "description": "Electronic gadgets and accessories",
    "parent_category_id": "-1",
    "visibility": True,
    "show_in_menu": True,
    "sibling_order": 1,
    "last_modified_time": "2019-12-12T00:00:00+0530",
    "ondc_category_type": "",
}
CHILD = {
    "category_id": "4815000000044002",
    "name": "Phones",
    "url": "phones",
    "parent_category_id": "4815000000044001",
    "visibility": True,
    "show_in_menu": False,
    "sibling_order": 2,
    "last_modified_time": "2019-12-12T00:00:01+0530",
    "ondc_category_type": "electronics.phones",
}
DETAIL = {
    "4815000000044001": {
        **ROOT,
        "seo_title": "Electronics",
        "seo_keyword": "electronics",
        "seo_description": "Shop electronics",
        "custom_fields": [{"index": 1, "value": "Priority"}],
        "category_tax_preferences": [
            {"tax_specification": "inter", "tax_id": "954919000000015071", "tax_name": "IGST18"},
        ],
    },
    "4815000000044002": {
        **CHILD,
        "seo_title": "Phones",
        "seo_keyword": "phones, smart phones ,  mobiles",
        "seo_description": "Shop phones",
    },
}


# ── hermetic: mapper, codec, spec ───────────────────────────────────────────

def test_field_map_extracts_and_translates():
    decoded = CATEGORIES_TRANSLATOR.decode(DETAIL["4815000000044001"])
    values = decoded.values
    assert values["name"] == "Electronics"
    assert values["slug"] == "electronics"          # Zoho "url" → our slug
    assert values["is_visible"] is True             # Zoho "visibility"
    assert values["show_in_menu"] is True
    assert values["position"] == 1                  # Zoho "sibling_order"
    assert values["meta_title"] == "Electronics"
    assert values["meta_keywords"] == ["electronics"]      # one CSV string → a JSON array
    assert values["meta_description"] == "Shop electronics"


def test_seo_keyword_csv_codec_splits_trims_and_joins_back():
    codec = CODECS["csv_list"]
    assert codec.decode("phones, smart phones ,  mobiles") == ["phones", "smart phones", "mobiles"]
    assert codec.decode(" , ,") is None and codec.decode("") is None    # blank is "no keywords", never [""]
    assert codec.encode(["a", "b c"]) == "a, b c"
    assert codec.encode(None) is None


def test_every_field_map_local_is_a_real_column():
    columns = set(Category.__table__.c.keys())
    for spec in FIELDS:
        assert spec.local in columns, f"categories FIELDS.{spec.local} is not a column"


def test_owned_fields_are_derived_and_include_the_hierarchy():
    assert ZOHO_OWNED_CATEGORY_FIELDS == frozenset(CATEGORIES_TRANSLATOR.readable) | {"parent_id"}
    assert "position" in ZOHO_OWNED_CATEGORY_FIELDS and "slug" in ZOHO_OWNED_CATEGORY_FIELDS
    assert CATEGORIES_CONFIG.contract.owned_fields == ZOHO_OWNED_CATEGORY_FIELDS


def test_the_spec_declares_what_the_live_api_taught_us():
    """Each line was learned on the live /categories endpoint (2026-09-25)."""
    cfg = CATEGORIES_CONFIG
    # Zoho prepends a synthetic ROOT row (category_id "-1") unless told not to.
    assert cfg.list_params == {"include_root_category": "false"}
    # Zoho masters the tree; declaring BIDIRECTIONAL while refusing local edits contradicted itself.
    assert cfg.direction is SyncDirection.INBOUND
    # An incremental list never shows a delete, so the weekly full scan must be able to tombstone.
    assert cfg.strategy is SyncStrategyName.INCREMENTAL and cfg.soft_delete_missing and cfg.weekly_full_enabled
    assert cfg.contract.crosswalk and cfg.contract.identity_echo == ("zoho_id",)
    sync_registry.validate()          # boot-time spec check (columns, codecs, echo) still passes


def test_outbound_payload_requires_the_create_arguments():
    complete = Category(name="Electronics", slug="electronics", meta_keywords=["a", "b"])
    payload = CATEGORIES_TRANSLATOR.encode(complete, intent=WriteIntent.CREATE)
    assert payload["name"] == "Electronics" and payload["url"] == "electronics"
    assert payload["seo_keyword"] == "a, b"          # back to the shape Zoho documents

    with pytest.raises(TranslationError):
        CATEGORIES_TRANSLATOR.encode(Category(name="No slug"), intent=WriteIntent.CREATE)


# ── integration: engine ─────────────────────────────────────────────────────

@pytest.fixture
async def world(db):
    tenant = Tenant(tenant_code="CATSYNC", name="Cat Sync Ltd",
                    primary_contact_email="ops@catsync.example", status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code="CATSYNC-HQ", legal_name="Cat Sync HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


def _client(rows=None) -> FakeZohoClient:
    rows = rows if rows is not None else [ROOT, CHILD]
    client = FakeZohoClient()
    client.stub_list("/categories", [rows])
    for row in rows:
        client.stub("GET", f"/categories/{row['category_id']}", make_response(DETAIL[row["category_id"]]))
    return client


async def _run_full(db, world, client: FakeZohoClient | None = None):
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        engine = ZohoSyncEngine(db, client or _client())
        report = await engine.run(MODULE, "full")
    await db.commit()
    return report


async def _category(db, world, zoho_id: str) -> Category:
    with tenant_scope(world[0].id, world[1].id):
        # populate_existing: a row already in the session is refreshed, not reused stale.
        return await db.scalar(select(Category).where(Category.zoho_id == zoho_id)
                               .execution_options(include_deleted=True, populate_existing=True))


async def test_sync_creates_hierarchy_and_recomputes_bounds(db, world):
    tenant, org = world
    report = await _run_full(db, world)
    assert report.status in ("success", "partial")

    # The per-organization "zoho" taxonomy was provisioned by the DB trigger.
    with tenant_scope(tenant.id, org.id):
        taxonomy = await db.scalar(select(Taxonomy).where(Taxonomy.slug == "zoho"))
    assert taxonomy is not None and taxonomy.organization_id == org.id

    root = await _category(db, world, ROOT["category_id"])
    child = await _category(db, world, CHILD["category_id"])
    assert root is not None and child is not None
    assert root.taxonomy_id == taxonomy.id and child.taxonomy_id == taxonomy.id
    assert root.parent_id is None and child.parent_id == root.id
    assert root.is_root and not child.is_root
    assert root.lft < child.lft < child.rgt < root.rgt
    assert root.depth == 0 and child.depth == 1
    assert child.is_visible is True and child.show_in_menu is False
    assert root.meta_title == "Electronics"
    assert root.position == 1

    # Crosswalk + raw provenance live off the entity table.
    with tenant_scope(tenant.id, org.id):
        record = await db.scalar(select(SyncRecord).where(SyncRecord.module == MODULE,
                                                           SyncRecord.external_id == ROOT["category_id"]))
    assert record is not None and record.entity_id == root.id
    assert record.raw_source == "detail_fetch"
    # Zoho categories use the {index, value} custom-field shape, which the
    # generic flatten (api_name/label keyed) does not map — the full array
    # still survives in the raw document, and so do the tax preferences that
    # have no column yet.
    assert record.raw["custom_fields"] == [{"index": 1, "value": "Priority"}]
    assert record.raw["category_tax_preferences"][0]["tax_id"] == "954919000000015071"


async def test_the_list_call_asks_zoho_to_leave_the_synthetic_root_out(db, world):
    client = _client()
    await _run_full(db, world, client)
    list_call = next(c for c in client.calls if c["path"] == "/categories")
    assert list_call["params"]["include_root_category"] == "false"


async def test_seo_keywords_land_as_a_json_array_and_serialise(db, world):
    await _run_full(db, world)
    child = await _category(db, world, CHILD["category_id"])
    assert child.meta_keywords == ["phones", "smart phones", "mobiles"]

    # The API DTO used to declare ``dict``; a synced category with SEO keywords
    # then failed serialisation (a 500 on GET /api/categories/{ref}).
    with tenant_scope(world[0].id, world[1].id):
        fat = await service.get_category(db, str(child.uuid))
        out = CategoryOut.model_validate(fat)
    assert out.meta_keywords == ["phones", "smart phones", "mobiles"] and out.zoho_id == CHILD["category_id"]


async def test_resync_matches_identity_and_does_not_duplicate(db, world):
    await _run_full(db, world)
    first = await _category(db, world, ROOT["category_id"])
    first_id = first.id

    # Re-run with the same payloads: identity matches, nothing duplicates.
    await _run_full(db, world)
    count = await db.scalar(
        select(func.count()).select_from(Category).execution_options(include_deleted=True)
    )
    assert count == 2
    again = await _category(db, world, ROOT["category_id"])
    assert again.id == first_id


async def test_synced_row_local_edit_to_owned_field_is_refused(db, world):
    await _run_full(db, world)
    row = await _category(db, world, ROOT["category_id"])
    with tenant_scope(world[0].id, world[1].id):
        with pytest.raises(Exception) as excinfo:
            await service.update_category(
                db, str(row.uuid), CategoryUpdate(name="Renamed", row_version=row.row_version),
            )
    assert "owned by Zoho" in str(excinfo.value)


async def test_a_local_move_of_a_zoho_linked_category_is_refused(db, world):
    """The hook re-links ``parent_id`` from Zoho on every re-apply, so a local
    move would be silently undone — the hierarchy is Zoho's, like the fields."""
    await _run_full(db, world)
    child = await _category(db, world, CHILD["category_id"])
    with tenant_scope(world[0].id, world[1].id):
        with pytest.raises(Exception) as via_move:
            await service.move_category(db, str(child.uuid),
                                        CategoryMove(parent_id=None, row_version=child.row_version))
        with pytest.raises(Exception) as via_patch:
            await service.update_category(db, str(child.uuid),
                                          CategoryUpdate(parent_id=None, row_version=child.row_version))
    assert "parent_id" in str(via_move.value) and "owned by Zoho" in str(via_move.value)
    assert "owned by Zoho" in str(via_patch.value)


async def test_an_unresolvable_parent_is_queued_and_the_reconcile_lane_links_it(db, world):
    """A child whose parent is not in the crosswalk used to stay a silent root that
    nothing re-examined (an unchanged row never reaches the hook again). It now
    waits on sync.pending_references, and the generic reconcile lane — which
    writes a bare ``UPDATE … SET parent_id`` — links it without tripping the
    is_root CHECK."""
    tenant, org = world
    await _run_full(db, world, _client([CHILD]))            # the parent has not been listed yet
    child = await _category(db, world, CHILD["category_id"])
    assert child.parent_id is None
    with tenant_scope(tenant.id, org.id):
        waiters = (await db.scalars(select(PendingReference).where(PendingReference.module == MODULE))).all()
    assert [(w.external_id, w.waiting_table, w.waiting_column, w.waiting_id) for w in waiters] == [
        (ROOT["category_id"], "core.categories", "parent_id", child.id)]

    await _run_full(db, world, _client([ROOT, CHILD]))      # the parent arrives; the child is unchanged
    assert (await drain_pending_references(db, tenant_id=tenant.id)).linked == 1
    await db.commit()

    root = await _category(db, world, ROOT["category_id"])
    child = await _category(db, world, CHILD["category_id"])
    assert child.parent_id == root.id and child.is_root is False
    assert await db.scalar(select(func.count()).select_from(PendingReference)
                           .where(PendingReference.module == MODULE)) == 0


async def test_a_tombstoned_parent_does_not_break_its_children(db, world):
    """A parent soft-deleted upstream leaves live children pointing at it. The
    tree recompute laid such a child out as a root and set ``is_root = true``
    beside its parent_id — violating ck_categories_root_no_parent and failing the
    whole flush."""
    await _run_full(db, world)
    root = await _category(db, world, ROOT["category_id"])
    await db.execute(text("UPDATE core.categories SET deleted_at = now() WHERE id = :id"), {"id": root.id})
    await db.commit()

    # Zoho re-lists the child (it changed): its hook recomputes the taxonomy.
    changed = {**CHILD, "name": "Phones & Tablets", "last_modified_time": "2019-12-13T00:00:00+0530"}
    client = _client([changed])
    client.stub("GET", f"/categories/{CHILD['category_id']}",
                make_response({**DETAIL[CHILD["category_id"]], **changed}))
    report = await _run_full(db, world, client)
    assert report.errors == 0

    child = await _category(db, world, CHILD["category_id"])
    assert child.name == "Phones & Tablets"
    assert child.parent_id == root.id and child.is_root is False      # a parent it still names…
    assert child.depth == 0 and child.path == "/phones/"              # …but laid out as a root


# ── taxes: category_tax_preferences → tax.tax_assignments ───────────────────

TAX_INTER, TAX_INTRA = "954919000000015071", "954919000000015147"


def _prefs(*pairs):
    return [{"tax_specification": spec, "tax_id": tax_id, "tax_name": "x"} for spec, tax_id in pairs]


def _detail_with(prefs, **extra):
    return {**DETAIL[ROOT["category_id"]], "category_tax_preferences": prefs, **extra}


async def _synced_taxes(db, world, **ids) -> dict[str, TaxComponent]:
    """Tax components + the crosswalk rows the ``taxes`` module would have written for them."""
    tenant, org = world
    made = {}
    with tenant_scope(tenant.id, org.id):
        for external_id, (name, kind) in ids.items():
            component = TaxComponent(tenant_id=tenant.id, tax_name=name, tax_percentage=Decimal("18"), tax_type=kind)
            db.add(component)
            await db.flush()
            await upsert_record(db, tenant_id=tenant.id, source_system="zoho", module="taxes",
                                external_id=external_id, values={"entity_table": "tax.tax_components",
                                                                 "entity_id": component.id,
                                                                 "link_state": LinkState.LINKED})
            made[external_id] = component
    await db.commit()
    return made


def _root_client(prefs) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/categories", [[ROOT]])
    client.stub("GET", f"/categories/{ROOT['category_id']}", make_response(_detail_with(prefs)))
    return client


async def _tax_rows(db, world, zoho_id=ROOT["category_id"]):
    category = await _category(db, world, zoho_id)
    with tenant_scope(world[0].id, world[1].id):
        return await tax_crud.list_for_owner(db, "category", category.id)


async def test_zoho_tax_preferences_become_zoho_sourced_assignments(db, world):
    taxes = await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax"), TAX_INTRA: ("GST18", "tax_group")})
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER), ("intra", TAX_INTRA))))

    rows = await _tax_rows(db, world)
    assert {(r.tax_specification, r.tax_component_id, r.source_system) for r in rows} == {
        ("inter", taxes[TAX_INTER].id, "zoho"), ("intra", taxes[TAX_INTRA].id, "zoho")}
    assert all(r.position in (0, 1) and not r.is_pending for r in rows)

    # and the category's own API shape carries them, marked as Zoho's
    root = await _category(db, world, ROOT["category_id"])
    with tenant_scope(world[0].id, world[1].id):
        out = CategoryOut.model_validate(await service.get_category(db, str(root.uuid)))
    assert {(p.tax_specification, p.tax.tax_name, p.source_system) for p in out.tax_preferences} == {
        ("inter", "IGST18", "zoho"), ("intra", "GST18", "zoho")}


async def test_a_tax_zoho_names_but_we_have_not_synced_waits_and_is_never_silently_dropped(db, world):
    tenant, _ = world
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER))))
    (row,) = await _tax_rows(db, world)
    assert row.is_pending and row.external_ref == TAX_INTER and row.tax_component_id is None
    with tenant_scope(tenant.id, world[1].id):
        waiters = (await db.scalars(select(PendingReference).where(PendingReference.waiting_table == "tax.tax_assignments"))).all()
    assert [(w.module, w.external_id, w.waiting_column) for w in waiters] == [("taxes", TAX_INTER, "tax_component_id")]

    taxes = await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax")})      # the taxes module runs
    assert (await drain_pending_references(db, tenant_id=tenant.id)).linked == 1   # the reconcile lane
    await db.commit()
    await db.refresh(row)
    assert row.tax_component_id == taxes[TAX_INTER].id and not row.is_pending


async def test_a_zoho_side_change_replaces_the_zoho_rows(db, world):
    taxes = await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax"), TAX_INTRA: ("GST18", "tax_group")})
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER), ("intra", TAX_INTRA))))
    # Zoho drops the intra tax and moves the inter one to the other context
    changed = _root_client(_prefs(("intra", TAX_INTER)))
    changed.stub("GET", f"/categories/{ROOT['category_id']}", make_response(
        _detail_with(_prefs(("intra", TAX_INTER)), last_modified_time="2019-12-13T00:00:00+0530")))
    changed.stub_list("/categories", [[{**ROOT, "last_modified_time": "2019-12-13T00:00:00+0530"}]])
    await _run_full(db, world, changed)

    rows = await _tax_rows(db, world)
    assert [(r.tax_specification, r.tax_component_id) for r in rows] == [("intra", taxes[TAX_INTER].id)]


async def test_a_thin_list_row_says_nothing_about_taxes_and_clears_nothing(db, world):
    await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax")})
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER))))
    root = await _category(db, world, ROOT["category_id"])
    with tenant_scope(world[0].id, world[1].id):
        await hooks.after_category_upsert(root, dict(ROOT))              # a list row: no category_tax_preferences key
        assert len(await tax_crud.list_for_owner(db, "category", root.id)) == 1
        await hooks.after_category_upsert(root, {**ROOT, "category_tax_preferences": []})   # a detail that says "none"
        assert await tax_crud.list_for_owner(db, "category", root.id) == []


async def test_bad_tax_data_from_zoho_is_skipped_and_never_fails_the_page(db, world):
    """Two taxes for one context breaks the one-per-context rule; one category's bad data must not sink the run."""
    await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax"), TAX_INTRA: ("IGST5", "tax")})
    report = await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER), ("inter", TAX_INTRA))))
    assert report.errors == 0
    assert (await _category(db, world, ROOT["category_id"])) is not None
    assert await _tax_rows(db, world) == []


async def test_a_linked_category_refuses_a_local_tax_edit(db, world):
    await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax")})
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER))))
    root = await _category(db, world, ROOT["category_id"])
    with tenant_scope(world[0].id, world[1].id):
        with pytest.raises(Exception) as excinfo:
            await service.update_category(db, str(root.uuid), CategoryUpdate(tax_preferences=[],
                                                                            row_version=root.row_version))
    assert "tax_preferences" in str(excinfo.value) and "owned by Zoho" in str(excinfo.value)


async def test_the_backfill_replays_stored_documents_with_no_api_call(db, world):
    """Categories synced before assignments existed get theirs from the crosswalk's stored document."""
    from app.modules.categories.zoho.backfill import backfill_tax_preferences

    taxes = await _synced_taxes(db, world, **{TAX_INTER: ("IGST18", "tax")})
    await _run_full(db, world, _root_client(_prefs(("inter", TAX_INTER))))
    root = await _category(db, world, ROOT["category_id"])
    with tenant_scope(world[0].id, world[1].id):                       # the state before the feature: no rows
        await hooks.tax_assignments.replace_assignments(db, "category", root.id, [], source_system="zoho")
        assert await tax_crud.list_for_owner(db, "category", root.id) == []

        report = await backfill_tax_preferences(db)
        assert (report.scanned, report.replayed, report.skipped_thin) == (1, 1, 0)
        (row,) = await tax_crud.list_for_owner(db, "category", root.id)
        assert row.tax_component_id == taxes[TAX_INTER].id and row.source_system == "zoho"

        again = await backfill_tax_preferences(db)                      # idempotent: a diff, not an insert
        assert again.replayed == 1 and len(await tax_crud.list_for_owner(db, "category", root.id)) == 1
