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
                     "locations": copy.deepcopy(LOCATIONS), "users": copy.deepcopy(USERS)}

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
        return httpx.Response(404, json={"code": 5, "message": f"Invalid URL {path}"})

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
    assert sorted(enqueued) == sorted(
        (m, "scheduled") for m in
        ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users")
    )

    results = await run_all(db)
    assert {m: r["status"] for m, r in results.items()} == dict.fromkeys(results, RunStatus.SUCCEEDED)
    assert results["organizations"]["created"] == 1
    assert results["currencies"]["created"] == 2 and results["taxes"]["created"] == 2
    assert results["tax_exemptions"]["created"] == 2
    assert results["locations"]["created"] == 1 and results["users"]["created"] == 2

    # organizations: 1 list + 1 detail. taxes: 1 list + 2 details (index_then_detail).
    # currencies / tax_exemptions / locations / users: 1 list each.
    assert len(wire.requests) == 9 and wire.calls_to("/organizations/10229182") == 1
    assert wire.calls_to("/settings/taxes/982000000566009") == 1

    # the governor counted every call; the runs and events are recorded
    assert (await zoho_governor.snapshot())["used"] == 9
    # `run_all` executes every REGISTERED module, so `tax_groups` gets a run too
    # even though the planner never schedules it (direction=disabled).
    assert set(await db.scalars(select(ZohoSyncRun.module))) == {
        "organizations", "currencies", "taxes", "tax_groups", "tax_exemptions", "locations", "users",
    }
    assert await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                           .where(ZohoSyncEvent.event_type == "inserted")) == 10

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
    for module in ("currencies", "tax_exemptions", "locations", "users", "organizations"):
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
    for module in ("organizations", "currencies", "taxes", "tax_exemptions", "locations", "users"):
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
