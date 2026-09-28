"""The five Phase 5 masters, end to end, through the REAL platform.

Real: ZohoClient transport (URL building, envelope parsing, page_context
contract), governor on Redis, circuit breaker, engine switches, planner tick,
leased runs, apply gate, batched page apply, sync events, the CLI.
Fake: only the HTTP wire (Zoho's *documented* responses, docs/zoho-docs-md/)
and the OAuth token.

Run with ``-s`` to see the CLI tables:
    .venv/bin/python -m pytest tests/zoho_core/test_masters_e2e.py -s
"""

import copy
import re

import httpx
import pytest
from sqlalchemy import func, select

from app.modules.zoho.control import planner
from app.modules.zoho.control.models import RunStatus, ZohoSyncEvent, ZohoSyncRun
from app.modules.zoho.control.switches import zoho_switches
from app.modules.zoho.core import transport as transport_module
from app.modules.zoho.core.governor import zoho_governor
from app.modules.zoho.sync.registry import sync_registry

# ── Zoho's documented payloads ──────────────────────────────────────────────

ORG_DETAIL = {
    "organization_id": "10229182", "name": "Zillium Inc", "is_default_org": False, "account_created_date": "2012-02-15",
    "time_zone": "PST", "language_code": "en", "date_format": "dd MMM yyyy", "field_separator": " ",
    "fiscal_year_start_month": 0, "tax_group_enabled": True, "contact_name": "John Smith",
    "industry_type": "Services", "currency_code": "INR",
    "address": {"street_address1": "14 Main St", "city": "Chennai", "country": "India", "zip": "600001"},
}
ORG_LIST_ROW = {k: ORG_DETAIL[k] for k in ("organization_id", "name", "is_default_org", "currency_code")}

CURRENCIES = [
    {"currency_id": "982000000004012", "currency_code": "AUD", "currency_name": "AUD- Australian Dollar",
     "currency_symbol": "$", "price_precision": 2, "currency_format": "1,234,567.89", "is_base_currency": False,
     "exchange_rate": 54.12, "effective_date": "2013-09-04"},
    {"currency_id": "982000000004000", "currency_code": "INR", "currency_name": "INR- Indian Rupee",
     "currency_symbol": "₹", "price_precision": 2, "currency_format": "1,23,45,678.90", "is_base_currency": True},
]
TAXES = [
    {"tax_id": "982000000566009", "tax_name": "IGST18", "tax_percentage": 18, "tax_type": "tax",
     "tax_specific_type": "igst", "is_value_added": False, "is_default_tax": True, "is_editable": True},
    {"tax_id": "982000000566010", "tax_name": "CGST9", "tax_percentage": 9, "tax_type": "tax",
     "tax_specific_type": "cgst", "is_value_added": False, "is_default_tax": False, "is_editable": True},
]
TAX_EXEMPTIONS = [
    {"tax_exemption_id": "982000000566101", "tax_exemption_code": "BILL OF SUPPLY",
     "description": "Composition dealer", "type": "item", "type_formatted": "Item",
     "exemption_name": "", "exemption_type": "exempt", "exemption_type_formatted": "Exempt"},
    {"tax_exemption_id": "982000000566102", "tax_exemption_code": "SEZ SUPPLY",
     "description": "Supply to an SEZ unit", "type": "customer", "type_formatted": "Customer",
     "exemption_name": "SEZ", "exemption_type": "exempt", "exemption_type_formatted": "Exempt"},
]
LOCATIONS = [{
    "type": "general", "email": "willsmith@bowmanfurniture.com", "phone": "+1-925-921-9201",
    "address": {"city": "New York City", "state": "New York", "country": "U.S.A", "attention": "string",
                "state_code": "NY", "street_address1": "No:234,90 Church Street", "street_address2": "McMillan Avenue"},
    "location_id": "460000000038080", "location_name": "Head Office", "tax_settings_id": "460000000038080",
    "status": "active", "is_primary": True,
    "associated_series_ids": ["982000000870911", "982000000870915"], "auto_number_generation_id": "982000000870911",
    "is_all_users_selected": False, "associated_users": [{"user_id": "460000000036868", "user_name": "John Doe"}],
}]
# Categories, shaped like the LIVE /categories response (captured 2026-09-25):
# the list is hierarchical, top-level rows name parent "-1", and — unless the
# caller passes include_root_category=false — Zoho prepends a synthetic ROOT row
# (id "-1", blank timestamps) that nobody created.
CAT_ROOT = {"category_id": "-1", "name": "ROOT", "url": "rootcategory", "parent_category_id": "-1",
            "visibility": True, "show_in_menu": True, "sibling_order": 1, "depth": 0,
            "created_time": "", "last_modified_time": "", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": False}
CAT_SKIN = {"category_id": "954919000013143071", "name": "Skin Care", "url": "skin_care",
            "parent_category_id": "-1", "visibility": True, "show_in_menu": True, "sibling_order": 2,
            "depth": 0, "created_time": "2024-10-22T16:53:19+0530",
            "last_modified_time": "2026-09-19T10:07:53+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
CAT_SOAP = {"category_id": "954919000061486002", "name": "Bathing Soap & Bodywash", "url": "bathing_soap_bodywash",
            "parent_category_id": "954919000013143071", "visibility": True, "show_in_menu": True,
            "sibling_order": 1, "depth": 1, "created_time": "2026-08-04T21:47:33+0530",
            "last_modified_time": "2026-09-07T16:54:23+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
CAT_HAIR = {"category_id": "954919000013118048", "name": "Hair Care", "url": "hair_care",
            "parent_category_id": "-1", "visibility": True, "show_in_menu": True, "sibling_order": 1,
            "depth": 0, "created_time": "2024-10-22T16:23:25+0530",
            "last_modified_time": "2026-09-19T10:07:28+0530", "description": "", "ondc_category_type": "",
            "custom_fields": [], "documents": [], "has_active_items": True}
#: What only the DETAIL document adds (SEO block, GST defaults) — live shape. The tax ids are the
#: ones this wire's own /settings/taxes serves, so the `taxes` module (run first) has synced them.
CAT_DETAIL_EXTRA = {
    "seo_title": "", "seo_keyword": "", "seo_description": "", "parent_category_name": "",
    "category_tax_preferences": [
        {"tax_specification": "inter", "tax_specific_type": "igst", "tax_id": "982000000566009",
         "tax_name": "IGST18", "tax_percentage": 18.0, "new_tax_type": "tax"},
        {"tax_specification": "intra", "tax_specific_type": "tax", "tax_id": "982000000566010",
         "tax_name": "CGST9", "tax_percentage": 9.0, "new_tax_type": "tax"},
    ],
    "ancestors": [], "children": [],
}
CATEGORIES = [CAT_HAIR, CAT_SKIN, CAT_SOAP]        # hierarchical order: parent before child

# Brands, shaped like the LIVE (undocumented) /brands response (captured 2026-09-28):
# a flat, unpaginated, two-field list; the detail document adds nothing.
BRANDS = [
    {"brand_id": "954919000013118046", "name": "DABUR"},
    {"brand_id": "954919000013143235", "name": "HIMALAYA"},
]

USERS = [
    {"user_id": "982000000554041", "role_id": "982000000006005", "name": "Sujin Kumar",
     "email": "johndavid@zilliuminc.com", "user_role": "admin", "status": "active", "is_current_user": True,
     "photo_url": "https://contacts.zoho.com/file?ID=x&fs=thumb", "is_customer_segmented": False,
     "is_vendor_segmented": False, "user_type": "zoho"},
    {"user_id": "982000000554042", "role_id": "982000000006006", "name": "Asha Rao", "email": "asha@zilliuminc.com",
     "user_role": "staff", "status": "inactive", "is_current_user": False, "user_type": "zoho"},
]


class ZohoWire:
    """httpx handler answering like Zoho Books v3 (per the vendored docs)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.data = {"currencies": copy.deepcopy(CURRENCIES), "taxes": copy.deepcopy(TAXES),
                     "tax_exemptions": copy.deepcopy(TAX_EXEMPTIONS),
                     "locations": copy.deepcopy(LOCATIONS), "users": copy.deepcopy(USERS),
                     "categories": copy.deepcopy(CATEGORIES), "brands": copy.deepcopy(BRANDS)}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == "Zoho-oauthtoken test-token"
        assert request.url.params["organization_id"]
        path = request.url.path.removeprefix("/books/v3")
        paged = {"page_context": {"page": 1, "per_page": 200, "has_more_page": False}}
        if path == "/organizations":
            return self._ok({"organizations": [ORG_LIST_ROW]})
        if match := re.fullmatch(r"/organizations/(\d+)", path):
            assert match.group(1) == "10229182"
            return self._ok({"organization": ORG_DETAIL})
        if path == "/settings/currencies":                       # documented WITHOUT page_context
            return self._ok({"currencies": self.data["currencies"]})
        if path == "/settings/taxes":
            return self._ok({"taxes": self.data["taxes"], **paged})
        if match := re.fullmatch(r"/settings/taxes/(\d+)", path):    # index_then_detail
            detail = next((t for t in self.data["taxes"] if t["tax_id"] == match.group(1)), None)
            if detail is None:
                return httpx.Response(404, json={"code": 1001, "message": "Tax not found"})
            return self._ok({"tax": detail})
        if path == "/settings/taxexemptions":                    # documented WITHOUT page_context
            return self._ok({"tax_exemptions": self.data["tax_exemptions"]})
        if path == "/locations":                                 # documented WITHOUT page_context
            return self._ok({"locations": self.data["locations"]})
        if path == "/users":
            assert request.url.params["filter_by"] == "Status.All"
            return self._ok({"users": self.data["users"], **paged})
        if path == "/categories":
            return self._categories_list(request, paged)
        if path == "/brands":
            # live: per_page/page/last_modified_time are all silently ignored.
            return self._ok({"brands": self.data["brands"]})
        if match := re.fullmatch(r"/categories/(-?\d+)", path):      # index_then_detail
            rows = [CAT_ROOT, *self.data["categories"]]
            detail = next((c for c in rows if c["category_id"] == match.group(1)), None)
            if detail is None:
                return httpx.Response(404, json={"code": 1001, "message": "Category not found"})
            return self._ok({"category": {**detail, **CAT_DETAIL_EXTRA}})
        return httpx.Response(404, json={"code": 5, "message": f"Invalid URL {path}"})

    def _categories_list(self, request: httpx.Request, paged: dict) -> httpx.Response:
        """Live behaviour: ROOT unless include_root_category=false; a modified-since
        filter that only accepts the ``+0000`` spelling (``…Z`` is a 400)."""
        params = request.url.params
        rows = list(self.data["categories"])
        if params.get("include_root_category") != "false":
            rows = [CAT_ROOT, *rows]
        since = params.get("last_modified_time")
        if since is not None:
            if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", since):
                return httpx.Response(400, json={"code": 2, "message": "Invalid value passed for last_modified_time"})
            from app.modules.sync.translation import CODECS

            floor = CODECS["zoho_datetime"].decode(since)
            # Live: ROOT (blank time) is returned by every filtered call unless excluded.
            rows = [r for r in rows if not r["last_modified_time"]
                    or CODECS["zoho_datetime"].decode(r["last_modified_time"]) >= floor]
        return self._ok({"categories": rows, **paged})

    @staticmethod
    def _ok(body: dict) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "message": "success", **body})

    def calls_to(self, path: str) -> int:
        return sum(1 for r in self.requests if r.url.path.endswith(path))


class StubTokens:
    async def get_token(self) -> str:
        return "test-token"

    async def invalidate(self, token: str | None = None) -> None:  # pragma: no cover
        pass


@pytest.fixture
async def wire(db, redis_available, monkeypatch):
    """Every ZohoClient the platform builds talks to the fake wire."""
    from app.core.conf import settings

    # The connection must name the organization the wire actually serves: the
    # engine attaches synced rows to the organization node whose `zoho_id` is
    # ZOHO_ORGANIZATION_ID (`zoho/control/tenancy.py`), and a canonical master
    # such as `currency.currencies` requires one. Point it at ORG_DETAIL.
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", ORG_DETAIL["organization_id"])
    wire = ZohoWire()

    # A subclass, not a factory function: modules imported lazily afterwards
    # evaluate annotations like ``ZohoClient | None`` (a function breaks `|`).
    class WiredClient(transport_module.ZohoClient):
        def __init__(self, **kwargs):
            super().__init__(http=httpx.AsyncClient(transport=httpx.MockTransport(wire)),
                             token_manager=StubTokens(), **kwargs)

    monkeypatch.setattr(transport_module, "ZohoClient", WiredClient)
    zoho_switches.invalidate()
    await zoho_governor.reset_day()
    yield wire
    await zoho_governor.reset_day()
    from app.database.db import engine

    await engine.dispose()          # the CLI/switches used the pooled engine on this test's loop


async def run_all(db) -> dict[str, dict]:
    """What the worker does for each enqueued lane — execute_leased_run.

    ``organizations`` goes first, always: it is the module that creates the
    organization node the Zoho connection points at (``ZOHO_ORGANIZATION_ID``),
    and the org-scoped masters — ``currency.currencies`` above all — cannot
    place a row until it exists. Registry order is import order, so relying on
    it made this test pass or fail depending on which test module ran before it.
    """
    from app.tasks.zoho_sync import execute_leased_run

    modules = sorted(sync_registry.all(), key=lambda d: d.name != "organizations")
    results = {}
    for defn in modules:
        client = transport_module.ZohoClient(default_module=defn.name)
        try:
            results[defn.name] = await execute_leased_run(
                db, client, module_name=defn.name, lane="scheduled", mode=None, trigger="planner")
        finally:
            await client.aclose()
    return results


async def test_the_planner_schedules_every_master_and_the_runs_mirror_them(db, wire, monkeypatch):
    from app.core.conf import settings

    monkeypatch.setattr(settings, "ZOHO_PLANNER_MAX_CONCURRENT_RUNS", 10)
    enqueued = []
    await planner.tick(db, enqueue=lambda module, lane, mode: enqueued.append((module, lane)))
    # `tax_groups` is registered DISABLED (Zoho documents no list endpoint), so
    # the planner schedules every master except that one.
    assert sorted(m for m, lane in enqueued if lane == "scheduled") == sorted(
        ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users", "categories", "brands")
    )
    # `categories` is the one INCREMENTAL master, so it alone also gets the weekly
    # full-reconcile lane — the only scan that can see a category Zoho deleted.
    assert [m for m, lane in enqueued if lane == "weekly_full"] == ["categories"]

    results = await run_all(db)
    assert {m: r["status"] for m, r in results.items()} == dict.fromkeys(results, RunStatus.SUCCEEDED)
    assert results["organizations"]["created"] == 1
    assert results["currencies"]["created"] == 2 and results["taxes"]["created"] == 2
    assert results["tax_exemptions"]["created"] == 2
    assert results["locations"]["created"] == 1 and results["users"]["created"] == 2
    assert results["categories"]["created"] == 3          # the synthetic ROOT is NOT one of them
    assert results["brands"]["created"] == 2

    # organizations: 1 list + 1 detail. taxes: 1 list + 2 details, categories: 1 list + 3 details
    # (index_then_detail). currencies / tax_exemptions / locations / users / brands: 1 list each.
    assert len(wire.requests) == 14 and wire.calls_to("/organizations/10229182") == 1
    assert wire.calls_to("/settings/taxes/982000000566009") == 1
    assert wire.calls_to("/categories/-1") == 0           # ROOT was never even listed
    assert wire.calls_to("/brands") == 1 and wire.calls_to("/brands/954919000013118046") == 0

    # the governor counted every call; the runs and events are recorded
    assert (await zoho_governor.snapshot())["used"] == 14
    # `run_all` executes every REGISTERED module, so `tax_groups` gets a run too
    # even though the planner never schedules it (direction=disabled).
    assert set(await db.scalars(select(ZohoSyncRun.module))) == {
        "organizations", "currencies", "taxes", "tax_groups", "tax_exemptions", "locations", "users",
        "categories", "brands",
    }
    assert await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                           .where(ZohoSyncEvent.event_type == "inserted")) == 15

    from app.modules.locations.model import ZohoLocation
    from app.modules.zoho_users.model import ZohoUser

    head_office = await db.scalar(select(ZohoLocation))
    assert head_office.address_state_code == "NY" and head_office.associated_users[0]["user_name"] == "John Doe"
    inactive = await db.scalar(select(ZohoUser).where(ZohoUser.zoho_status == "inactive"))
    assert inactive.name == "Asha Rao"                      # Status.All: inactive users are mirrored too
    assert inactive.status == "active"                      # OUR record status ≠ Zoho's (zoho_status)

    # Tenancy: everything the sync wrote belongs to the Zoho tenant and is
    # attached to the organization node the Zoho org became.
    from app.modules.organizations.model import Organization

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    assert org.parent_id is None and org.org_type == "legal_entity" and org.org_code == "ZOHO-10229182"
    assert head_office.tenant_id == org.tenant_id and inactive.created_by_name == "system:zoho-sync"


async def test_a_second_pass_writes_nothing_and_a_zoho_change_lands(db, wire):
    await run_all(db)
    wire.data["taxes"][1]["tax_percentage"] = 6              # someone edits CGST in Zoho
    second = await run_all(db)

    # taxes is index_then_detail: each record is applied twice (the listed row,
    # then the detail document), so two taxes make four applies — the edited
    # CGST detail is the one update, the other three are unchanged.
    assert second["taxes"]["updated"] == 1 and second["taxes"]["unchanged"] == 3
    for module in ("currencies", "tax_exemptions", "locations", "users", "organizations", "categories", "brands"):
        assert second[module]["created"] == second[module]["updated"] == 0, module

    # Scoped to the module: `organizations` is index-then-detail, so its own
    # first-pass detail write is an "updated" event too.
    changed = await db.scalar(select(ZohoSyncEvent).where(ZohoSyncEvent.event_type == "updated",
                                                          ZohoSyncEvent.module == "taxes"))
    assert changed.diff == {"tax_percentage": ["9.0000", "6"]}


async def test_the_cli_runs_the_same_pipeline(db, wire, capsys):
    from app.modules.zoho import cli

    assert await cli.cmd_sync(None, None) == 0
    assert await cli.cmd_status() == 0
    assert await cli.cmd_runs(10, None) == 0
    out = capsys.readouterr().out
    print(out)                                               # visible with -s
    for module in ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users", "categories",
                  "brands"):
        assert module in out
    assert "failed" not in out


async def test_the_read_endpoints_serve_locations_and_users(db, wire):
    from types import SimpleNamespace

    from app.database.db import get_db
    from app.main import app
    from app.modules.users.deps import get_current_user

    await run_all(db)

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, email="u@x.com")
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
            locations = (await api.get("/api/zoho/locations", params={"status": "active"})).json()["data"]
            assert [loc["location_name"] for loc in locations] == ["Head Office"]
            assert locations[0]["is_primary"] is True
            by_email = (await api.get("/api/zoho/users/JOHNDAVID@zilliuminc.com")).json()["data"]
            assert by_email["zoho_id"] == "982000000554041"
            inactive = (await api.get("/api/zoho/users", params={"status": "inactive"})).json()["data"]
            assert [u["name"] for u in inactive] == ["Asha Rao"]
            assert (await api.get("/api/zoho/locations/404404")).status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_categories_end_to_end_through_the_real_transport(db, wire, monkeypatch):
    """The live-verified behaviours of the categories adapter, on the real pipeline.

    Each assertion here is something the first cut of the adapter got wrong on
    the live API and the unit-level FakeZohoClient could not show: the synthetic
    ROOT row, the modified-since spelling, the hierarchy landing through the
    crosswalk, and a Zoho-side delete reaching the tree.
    """
    from app.core.conf import settings
    from app.modules.categories.model import Category
    from app.modules.sync.models import SyncRecord
    from app.tasks.zoho_sync import execute_leased_run

    await run_all(db)

    # 1. ROOT is asked NOT to be listed, and did not become a category.
    first_list = next(r for r in wire.requests if r.url.path.endswith("/categories"))
    assert first_list.url.params["include_root_category"] == "false"
    rows = {c.zoho_id: c for c in (await db.scalars(select(Category))).all()}
    assert set(rows) == {CAT_HAIR["category_id"], CAT_SKIN["category_id"], CAT_SOAP["category_id"]}

    # 2. The hierarchy landed through the crosswalk, with coherent bounds.
    hair, skin, soap = (rows[c["category_id"]] for c in (CAT_HAIR, CAT_SKIN, CAT_SOAP))
    assert hair.parent_id is None and hair.is_root and skin.is_root
    assert soap.parent_id == skin.id and not soap.is_root and soap.depth == 1
    assert skin.lft < soap.lft < soap.rgt < skin.rgt
    assert soap.slug == "bathing_soap_bodywash" and soap.position == 1 and soap.meta_keywords is None

    # 3. Identity, gate state and the raw DETAIL document live on the crosswalk,
    #    tax preferences included (they have no column yet).
    record = await db.scalar(select(SyncRecord).where(SyncRecord.module == "categories",
                                                       SyncRecord.external_id == CAT_SOAP["category_id"]))
    assert record.entity_id == soap.id and record.raw_source == "detail_fetch"
    assert [p["tax_specification"] for p in record.raw["category_tax_preferences"]] == ["inter", "intra"]

    # 3b. …and they are ALSO real assignments now: every category carries one tax per context, resolved
    #     through the crosswalk to the components the `taxes` module synced, marked as Zoho's.
    from app.modules.taxes.assignment import TaxAssignment
    from app.modules.taxes.component import TaxComponent

    names = {c.id: c.tax_name for c in (await db.scalars(select(TaxComponent))).all()}
    assignments = (await db.scalars(select(TaxAssignment).where(TaxAssignment.owner_type_code == "category"))).all()
    assert len(assignments) == 6 and all(a.source_system == "zoho" and not a.is_pending for a in assignments)
    assert {(a.owner_id, a.tax_specification): names[a.tax_component_id] for a in assignments} == {
        (c.id, spec): tax for c in (hair, skin, soap) for spec, tax in (("inter", "IGST18"), ("intra", "CGST9"))}

    # 4. A Zoho-side rename arrives through the modified-since filter — and only
    #    that row is rewritten. (Live: the filter takes +0000 and 400s on a "Z".)
    wire.data["categories"][2].update(name="Bath Soaps", last_modified_time="2026-09-25T10:00:00+0530")
    await run_all(db)
    filtered = [r for r in wire.requests if r.url.path.endswith("/categories") and "last_modified_time" in r.url.params]
    assert filtered and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}",
                                     filtered[-1].url.params["last_modified_time"])
    await db.refresh(soap)
    assert soap.name == "Bath Soaps"
    updated_ids = set(await db.scalars(select(ZohoSyncEvent.local_id).where(
        ZohoSyncEvent.module == "categories", ZohoSyncEvent.event_type == "updated",
        ZohoSyncEvent.zoho_id == CAT_SOAP["category_id"])))
    assert updated_ids == {soap.id}

    # 5. A category deleted in Zoho is only ever visible to a FULL scan; with the
    #    operator switch on, that scan tombstones it on BOTH sides.
    monkeypatch.setattr(settings, "ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING", True)
    del wire.data["categories"][2]
    client = transport_module.ZohoClient(default_module="categories")
    try:
        result = await execute_leased_run(db, client, module_name="categories", lane="weekly_full",
                                          mode="full", trigger="planner")
    finally:
        await client.aclose()
    assert result["status"] == RunStatus.SUCCEEDED and result["soft_deleted"] == 1
    db.expire_all()
    gone = await db.scalar(select(Category).where(Category.zoho_id == CAT_SOAP["category_id"])
                           .execution_options(include_deleted=True))
    assert gone.deleted_at is not None
    tombstone = await db.scalar(select(SyncRecord).where(SyncRecord.module == "categories",
                                                          SyncRecord.external_id == CAT_SOAP["category_id"]))
    assert tombstone.remote_deleted_at is not None
    assert await db.scalar(select(func.count()).select_from(Category)) == 2      # hair, skin live
