"""Apply gate — the pure decision table and its effect through the engine."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.modules.zoho.control.models import ZohoSyncEvent
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.zoho.sync.apply import (
    Incoming,
    Outcome,
    RowState,
    decide,
    payload_hash,
    provenance_rank,
)
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.registry import sync_registry
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

T0 = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
H1, H2 = b"\x01" * 32, b"\x02" * 32


def incoming(modified=T0, digest=H1, source="detail_fetch"):
    return Incoming(modified=modified, payload_hash=digest, source=source)


def row(modified=T0, digest=H1, source="detail_fetch", **kw):
    return RowState(zoho_last_modified_time=modified, zoho_raw_hash=digest, sync_source=source, **kw)


# ── decision table ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("stored", "payload", "outcome", "write_raw"),
    [
        (None, incoming(), Outcome.INSERTED, True),
        (row(), incoming(modified=T0 - timedelta(seconds=1)), Outcome.STALE_IGNORED, False),
        (row(), incoming(), Outcome.UNCHANGED, False),                                  # same version + hash
        (row(), incoming(digest=H2, source="list:full"), Outcome.UNCHANGED, False),     # thinner, same version
        (row(), incoming(digest=H2), Outcome.UPDATED, True),                            # same version, new detail
        (row(), incoming(modified=T0 + timedelta(minutes=1), digest=H2, source="list:full"),
         Outcome.UPDATED, False),                                                       # newer but thin: keep raw
        (row(source="list:full"), incoming(modified=T0 + timedelta(minutes=1), digest=H2),
         Outcome.UPDATED, True),                                                        # detail beats list
        (row(modified=None), incoming(modified=None), Outcome.UNCHANGED, False),        # undated, same hash
        (row(modified=None), incoming(modified=None, digest=H2), Outcome.UPDATED, True),
    ],
)
def test_decision_table(stored, payload, outcome, write_raw):
    decision = decide(stored, payload)
    assert decision.outcome is outcome
    assert decision.write_raw is write_raw


def test_tombstone_is_revived_only_by_newer_evidence():
    tombstoned = row(remote_deleted_at=T0 + timedelta(hours=1))
    assert decide(tombstoned, incoming()).outcome is Outcome.STALE_IGNORED
    newer = decide(tombstoned, incoming(modified=T0 + timedelta(hours=2), digest=H2))
    assert newer.outcome is Outcome.RESURRECTED and newer.revive
    # undated modules: being listed again IS the evidence
    assert decide(row(modified=None, remote_deleted_at=T0), incoming(modified=None)).revive


def test_legacy_v1_tombstone_counts_but_a_user_delete_does_not():
    legacy = row(deleted_at=T0 + timedelta(hours=1), legacy_tombstone=True)
    assert decide(legacy, incoming()).outcome is Outcome.STALE_IGNORED
    user_deleted = row(deleted_at=T0 + timedelta(hours=1))
    decision = decide(user_deleted, incoming(digest=H2))
    assert decision.outcome is Outcome.UPDATED and not decision.revive


def test_provenance_ranks():
    assert provenance_rank("nested:contacts") < provenance_rank("list:full") < provenance_rank("detail_fetch")
    assert provenance_rank("webhook") == provenance_rank("detail_fetch")


def test_any_order_of_snapshots_converges_to_the_newest():
    """Property: shuffled, duplicated, stale deliveries end at the newest version."""
    versions = [(T0 + timedelta(minutes=i), bytes([i]) * 32) for i in range(6)]
    rng = random.Random(7)
    for _ in range(200):
        deliveries = versions + rng.choices(versions, k=6)
        rng.shuffle(deliveries)
        state = None
        for modified, digest in deliveries:
            decision = decide(state, incoming(modified=modified, digest=digest))
            if decision.outcome.writes:
                state = row(modified=modified, digest=digest)
        assert state.zoho_last_modified_time == versions[-1][0]
        assert state.zoho_raw_hash == versions[-1][1]


def test_hash_ignores_key_order_and_volatile_keys():
    a = {"name": "Acme", "total": 10, "total_formatted": "₹10.00", "nested": {"x_formatted": "1", "x": 1}}
    b = {"nested": {"x": 1, "x_formatted": "one"}, "total_formatted": "INR 10", "total": 10, "name": "Acme"}
    keys = ["*_formatted"]
    assert payload_hash(a, keys) == payload_hash(b, keys)
    assert payload_hash(a, keys) != payload_hash({**a, "total": 11}, keys)
    assert payload_hash(a) != payload_hash(b)                 # without the volatile list they differ


# ── through the engine (real Postgres, fake Zoho) ───────────────────────────

ORG = {
    "organization_id": "10229182",
    "name": "Zillium Inc",
    "time_zone": "IST",
    "last_modified_time": "2026-09-18T10:00:00+0530",
}


def client_for(detail: dict, listed: dict | None = None) -> FakeZohoClient:
    client = FakeZohoClient()
    listed = listed or {k: detail[k] for k in ("organization_id", "name", "last_modified_time")}
    client.stub_list("/organizations", [[listed]])
    client.stub("GET", f"/organizations/{detail['organization_id']}", make_response(detail))
    return client


async def xmin(db) -> int:
    return int(await db.scalar(text("SELECT xmin::text::bigint FROM org_management.organizations LIMIT 1")))


async def test_identical_payload_writes_nothing(db):
    await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    before = await xmin(db)

    report = await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    assert report.unchanged == 1 and report.updated == 0
    assert await xmin(db) == before                            # no UPDATE → no WAL, no CDC event


async def test_detail_call_is_skipped_when_the_row_is_current(db):
    await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()

    client = client_for(ORG)
    report = await ZohoSyncEngine(db, client).run("organizations", "full")
    await db.commit()
    assert report.details_saved == 1
    assert [c["path"] for c in client.calls] == ["/organizations"]     # list only: 1 call, not 2


async def test_stale_payload_is_ignored_and_journalled(db):
    newer = {**ORG, "name": "Zillium Renamed", "last_modified_time": "2026-09-18T11:00:00+0530"}
    await ZohoSyncEngine(db, client_for(newer)).run("organizations", "full")
    await db.commit()

    # A lagging replica / late webhook delivers the OLD version.
    defn = sync_registry.get("organizations")
    result = await ZohoSyncEngine(db).apply_payload(defn, ORG, source="webhook")
    await db.commit()
    assert result.outcome is Outcome.STALE_IGNORED

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    assert org.name == "Zillium Renamed"
    stale = (await db.scalars(select(ZohoSyncEvent).where(ZohoSyncEvent.event_type == "stale_ignored"))).all()
    assert len(stale) == 1 and stale[0].message == "older_than_stored"


async def test_thin_payload_never_overwrites_the_detail_document(db):
    detail = {**ORG, "industry_type": "Services", "address": {"city": "Palo Alto"}}
    await ZohoSyncEngine(db, client_for(detail)).run("organizations", "full")
    await db.commit()

    newer_list_row = {"organization_id": "10229182", "name": "Zillium Renamed",
                      "last_modified_time": "2026-09-18T12:00:00+0530"}
    report = await ZohoSyncEngine(db, client_for(detail, listed=newer_list_row)).run("organizations", "index")
    await db.commit()
    assert report.updated == 1

    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    assert org.name == "Zillium Renamed"                        # mapped columns follow the newer version
    assert org.address_city == "Palo Alto"                      # missing keys never null a column

    # Provenance is the crosswalk's business now; the rule is unchanged.
    record = await db.scalar(select(SyncRecord).where(SyncRecord.module == "organizations"))
    assert record.raw["industry_type"] == "Services"            # the detail document is kept
    assert record.raw_source == "detail_fetch"
    assert record.source_modified_at == datetime(2026, 9, 18, 6, 30, tzinfo=UTC)


async def test_version_and_bookkeeping_columns(db):
    await ZohoSyncEngine(db, client_for(ORG)).run("organizations", "full")
    await db.commit()
    org = await db.scalar(select(Organization).where(Organization.zoho_id == "10229182"))
    assert org.uuid is not None and org.row_version >= 1
    record = await db.scalar(select(SyncRecord).where(SyncRecord.module == "organizations"))
    # index_then_detail writes twice: the listed row, then the detail over it.
    assert record.sync_version == 2
    assert record.raw_hash and record.raw_synced_at and record.raw_source == "detail_fetch"

    changed = {**ORG, "name": "New", "last_modified_time": "2026-09-18T13:00:00+0530"}
    await ZohoSyncEngine(db, client_for(changed)).run("organizations", "full")
    await db.commit()
    await db.refresh(org)
    await db.refresh(record)
    assert record.sync_version == 4 and org.name == "New"
