"""Record-level sync events and the guarded soft-delete (real Postgres, fake Zoho)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.conf import settings
from app.modules.zoho.control.events import build_diff
from app.modules.zoho.control.models import RunStatus, ZohoSyncEvent, ZohoSyncRun
from app.modules.zoho.core.errors import ZohoBudgetDeferred
from app.modules.organizations.model import Organization
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.tasks.zoho_sync import execute_leased_run
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

ORG = {
    "organization_id": "10229182",
    "name": "Zillium Inc",
    "email": "johnsmith@zillum.com",
    "phone": "+91-9876543210",
    "time_zone": "IST",
    "currency_code": "INR",
    "last_modified_time": "2026-09-18T10:00:00+0530",
}


def client_for(*orgs: dict) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/organizations", [[{"organization_id": o["organization_id"], "name": o["name"]} for o in orgs]])
    for org in orgs:
        client.stub("GET", f"/organizations/{org['organization_id']}", make_response(org))
    return client


async def events(db, **filters):
    stmt = select(ZohoSyncEvent).order_by(ZohoSyncEvent.id)
    for key, value in filters.items():
        stmt = stmt.where(getattr(ZohoSyncEvent, key) == value)
    return list((await db.scalars(stmt)).all())


# ── diff building ───────────────────────────────────────────────────────────

def test_diff_masks_personal_data_and_ignores_numeric_noise():
    changed, diff = build_diff(
        {"name": "Old", "phone": "+91-9876543210", "total": Decimal("12.50"), "email": None},
        {"name": "New", "phone": "+91-9999900000", "total": 12.5, "email": "a@b.example"},
    )
    assert changed == ["email", "name", "phone"]                 # 12.50 == 12.5 is not a change
    assert diff["name"] == ["Old", "New"]
    assert diff["phone"][0].endswith("3210") and "9876" not in diff["phone"][0]
    assert diff["email"][1].endswith("mple") and "@" not in diff["email"][1]


def test_diff_truncates_long_values():
    _, diff = build_diff({"notes": ""}, {"notes": "x" * 2000})
    assert len(diff["notes"][1]) <= 501


# ── events from the engine ──────────────────────────────────────────────────

async def test_insert_then_update_then_noop_are_recorded(db):
    run_id = uuid.uuid4()
    await ZohoSyncEngine(db, client_for(ORG), run_id=run_id).run("organizations", "full")
    await db.commit()

    # index_then_detail: the listed row is inserted, then the detail completes it.
    inserted = await events(db, module="organizations", zoho_id="10229182")
    assert [e.event_type for e in inserted] == ["inserted", "updated"]
    assert inserted[0].run_id == run_id and inserted[0].direction == "pull"
    assert inserted[0].local_id is not None

    changed = {**ORG, "name": "Zillium Renamed", "last_modified_time": "2026-09-18T11:00:00+0530"}
    await ZohoSyncEngine(db, client_for(changed)).run("organizations", "full")
    await db.commit()
    await ZohoSyncEngine(db, client_for(changed)).run("organizations", "full")   # no-op
    await db.commit()

    history = await events(db, module="organizations", zoho_id="10229182")
    # insert + detail, then the rename (carried by the detail). The thin index
    # row is undated and strictly thinner than the stored document, so it is
    # correctly a no-op both times rather than a write per scan.
    assert [e.event_type for e in history] == ["inserted", "updated", "updated"]
    rename = history[2]
    assert rename.changed_fields == ["legal_name", "name"]   # a Zoho-linked node's legal name follows Zoho
    assert rename.diff == {"name": ["Zillium Inc", "Zillium Renamed"],
                           "legal_name": ["Zillium Inc", "Zillium Renamed"]}


async def test_events_can_be_disabled(db, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_SYNC_EVENTS_ENABLED", False)
    await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    assert await events(db) == []


# ── the soft-delete guard ───────────────────────────────────────────────────

@pytest.fixture
def org_with_soft_delete(monkeypatch):
    from app.modules.zoho.sync.registry import sync_registry

    defn = sync_registry.get("organizations")
    monkeypatch.setattr(defn, "config", defn.config.model_copy(update={"soft_delete_missing": True}))
    return defn


async def _seed_orgs(db, count: int) -> None:
    """Seed orgs the way a real sync leaves them: entity row + crosswalk row.

    The reconciliation scan reads the CROSSWALK for "what we hold", not the
    entity table — which is the point of the split. A row inserted with a
    ``zoho_id`` echo but no crosswalk entry was never synced, and the sync is
    right not to tombstone it.
    """
    from app.database.tenancy import write_tenant_id
    from app.modules.sync.crosswalk import upsert_record

    tenant_id = await write_tenant_id(db)
    for i in range(count):
        external_id = f"90000{i:04d}"
        org = Organization(zoho_id=external_id, name=f"Org {i}")
        db.add(org)
        await db.flush()
        await upsert_record(
            db, tenant_id=tenant_id, source_system="zoho", module="organizations",
            external_id=external_id,
            values={"entity_table": Organization.__table__.fullname, "entity_id": org.id,
                    "link_state": "linked", "raw_source": "list:full"},
        )
    await db.commit()


async def test_soft_delete_missing_is_off_by_default(db, org_with_soft_delete):
    await _seed_orgs(db, 3)
    report = await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    assert report.soft_deleted == 0
    live = await db.scalar(select(Organization.id).where(Organization.zoho_id == "900000000"))
    assert live is not None


async def test_mass_delete_guard_refuses_a_partial_scan(db, org_with_soft_delete, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING", True)
    monkeypatch.setattr(settings, "ZOHO_SYNC_MASS_DELETE_MIN", 2)
    await _seed_orgs(db, 5)                                  # 5 missing > limit of 2
    report = await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    assert report.soft_deleted == 0


async def test_small_genuine_deletions_are_tombstoned_with_events(db, org_with_soft_delete, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING", True)
    monkeypatch.setattr(settings, "ZOHO_SYNC_MASS_DELETE_MIN", 5)
    await _seed_orgs(db, 2)
    report = await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    assert report.soft_deleted == 2
    tombstones = await events(db, event_type="tombstoned")
    assert {e.zoho_id for e in tombstones} == {"900000000", "900000001"}


# ── leased runs ─────────────────────────────────────────────────────────────

async def test_leased_run_records_the_run_and_links_events(db):
    result = await execute_leased_run(
        db, client_for(ORG), module_name="organizations", lane="manual", mode="full", trigger="test"
    )
    assert result["status"] == RunStatus.SUCCEEDED and result["created"] == 1

    run = await db.get(ZohoSyncRun, uuid.UUID(result["run_id"]))
    await db.refresh(run)
    assert run.status == RunStatus.SUCCEEDED and run.created == 1 and run.finished_at
    linked = await events(db, run_id=run.id)
    assert [e.event_type for e in linked] == ["inserted", "updated"]   # index, then detail


async def test_leased_run_skips_when_the_lane_is_busy(db):
    from app.modules.zoho.control.runs import acquire_run

    await acquire_run(db, module="organizations", lane="manual", trigger="test", owner="other-worker")
    result = await execute_leased_run(
        db, client_for(ORG), module_name="organizations", lane="manual", mode="full", trigger="test"
    )
    assert result == {"status": "skipped", "reason": "lane_busy"}


async def test_budget_refusal_yields_instead_of_failing(db):
    client = FakeZohoClient()
    client.stub("GET", "/organizations", ZohoBudgetDeferred("paced", reason="pacing"))
    result = await execute_leased_run(
        db, client, module_name="organizations", lane="scheduled", mode="full", trigger="test"
    )
    assert result["status"] == RunStatus.YIELDED and result["reason"] == "pacing"
    run = await db.get(ZohoSyncRun, uuid.UUID(result["run_id"]))
    await db.refresh(run)
    assert run.stop_reason == "pacing"
