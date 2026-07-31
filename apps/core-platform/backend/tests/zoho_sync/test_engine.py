"""Sync engine integration tests (real Postgres, fake Zoho client).

Covers: full sync with inline N+1 detail fetches, identity matching
(create vs update), soft-delete revival, stats/cursor bookkeeping and
per-record error isolation — using the organizations module as the
registered guinea pig.
"""

import pytest

from app.modules.zoho.organizations.model import ZohoOrganization
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.models import ZohoSyncStat
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

# Payload shapes from docs/zoho-docs-md/organizations.md
LIST_ORG = {
    "organization_id": "10229182",
    "name": "Zillium Inc",
    "contact_name": "John Smith",
    "email": "johnsmith@zillum.com",
    "is_default_org": False,
    "language_code": "en",
    "fiscal_year_start_month": 0,
    "account_created_date": "2012-02-15",
    "time_zone": "PST",
    "is_org_active": True,
    "currency_code": "USD",
}

DETAIL_ORG = {
    **LIST_ORG,
    "date_format": "dd MMM yyyy",
    "field_separator": " ",
    "tax_group_enabled": True,
    "industry_type": "Services",
    "address": {
        "street_address1": "14 Main St",
        "street_address2": "Suite 2",
        "city": "Palo Alto",
        "state": "CA",
        "country": "U.S.A",
        "zip": "94301",
    },
    "custom_fields": [{"api_name": "cf_zone", "value": "West"}],
}


def _client_with_org(detail: dict = DETAIL_ORG) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/organizations", [[LIST_ORG]])
    client.stub("GET", "/organizations/10229182", make_response(detail))
    return client


async def test_full_sync_creates_row_with_detail_payload(db):
    engine = ZohoSyncEngine(db, _client_with_org())
    report = await engine.run("organizations", "full")
    await db.commit()

    assert report.status == "success"
    assert report.created == 1 and report.updated == 0 and report.errors == 0

    row = await db.scalar(
        ZohoOrganization.__table__.select().with_only_columns(ZohoOrganization.id).limit(1)
    )
    org = await db.get(ZohoOrganization, row)
    # Mapped from the DETAIL payload (proves the N+1 fetch happened)
    assert org.zoho_id == "10229182"
    assert org.name == "Zillium Inc"
    assert org.date_format == "dd MMM yyyy"
    assert org.address_city == "Palo Alto"
    assert org.tax_group_enabled is True
    assert org.field_separator is None            # " " normalised to NULL
    assert org.custom_fields == {"cf_zone": "West"}  # hstore round-trip
    assert org.zoho_raw["organization_id"] == "10229182"
    assert org.sync_status == SyncStatus.SYNCED.value
    assert org.synced_at is not None
    assert org.sync_logs and org.sync_logs[-1]["event"] == "inbound_upsert"

    # The engine hit list first, then the detail endpoint
    paths = [c["path"] for c in engine.client.calls]
    assert "/organizations" in paths and "/organizations/10229182" in paths


async def test_second_run_matches_identity_and_updates(db):
    engine = ZohoSyncEngine(db, _client_with_org())
    await engine.run("organizations", "full")
    await db.commit()

    changed = {**DETAIL_ORG, "name": "Zillium Renamed"}
    engine2 = ZohoSyncEngine(db, _client_with_org(changed))
    report = await engine2.run("organizations", "full")
    await db.commit()

    assert report.created == 0 and report.updated == 1
    org = await db.scalar(
        ZohoOrganization.__table__.select().with_only_columns(ZohoOrganization.name)
    )
    assert org == "Zillium Renamed"


async def test_resync_revives_soft_deleted_row(db):
    engine = ZohoSyncEngine(db, _client_with_org())
    await engine.run("organizations", "full")
    await db.commit()

    from sqlalchemy import select

    org = await db.scalar(select(ZohoOrganization).limit(1))
    org.soft_delete()
    await db.commit()

    # Gone from filtered queries...
    assert await db.scalar(select(ZohoOrganization).limit(1)) is None

    # ...but a re-sync matches it by zoho_id (include_deleted) — no duplicate.
    report = await ZohoSyncEngine(db, _client_with_org()).run("organizations", "full")
    await db.commit()
    assert report.created == 0 and report.updated == 1

    all_rows = (
        await db.scalars(select(ZohoOrganization).execution_options(include_deleted=True))
    ).all()
    assert len(all_rows) == 1


async def test_stats_are_maintained_per_module(db):
    from sqlalchemy import select

    await ZohoSyncEngine(db, _client_with_org()).run("organizations", "full")
    await db.commit()

    stat = await db.scalar(select(ZohoSyncStat).where(ZohoSyncStat.module_name == "organizations"))
    assert stat is not None
    assert stat.last_run_status == "success"
    assert stat.last_run_mode == "full"
    assert stat.total_records_synced == 1
    assert stat.records_created == 1
    assert stat.run_count == 1
    assert stat.last_sync_time is not None
    assert stat.last_full_sync_time is not None
    assert stat.last_zoho_id_synced == "10229182"


async def test_one_bad_record_does_not_sink_the_run(db):
    client = FakeZohoClient()
    # Second record has no organization_id -> per-record error, run continues
    client.stub_list("/organizations", [[LIST_ORG, {"name": "ghost, no id"}]])
    client.stub("GET", "/organizations/10229182", make_response(DETAIL_ORG))

    report = await ZohoSyncEngine(db, client).run("organizations", "full")
    await db.commit()

    assert report.created == 1
    assert report.errors == 1
    assert report.status == "partial"

    # The failure is journalled at row level
    from sqlalchemy import select

    from app.modules.zoho.sync.models import ZohoQueueLog

    log = await db.scalar(select(ZohoQueueLog).where(ZohoQueueLog.status == "failed"))
    assert log is not None and log.module_name == "organizations"


async def test_incremental_degrades_to_full_when_unsupported(db):
    """organizations has modified_since_param=None -> incremental == full."""
    engine = ZohoSyncEngine(db, _client_with_org())
    report = await engine.run("organizations", "incremental")
    await db.commit()
    assert report.mode == "full"
    assert report.created == 1


async def test_unknown_module_raises_not_found(db):
    from app.common.exception.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await ZohoSyncEngine(db, FakeZohoClient()).run("no-such-module")
