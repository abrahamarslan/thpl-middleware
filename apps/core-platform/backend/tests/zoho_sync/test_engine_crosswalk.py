"""The engine's crosswalk shape: entity table holds business columns only.

The module under test is a throwaway spec pointed at ``currency.currencies``
(the real currencies adapter lands in Phase 4). What matters here is the shape,
not the module: gate state in ``sync.sync_records``, history in
``sync.sync_payloads``, and an entity row carrying no sync columns at all.

The three behaviours worth proving are the ones the design review said a naive
split would silently break:

  * a payload that changes nothing writes no history row;
  * a locally deleted row is refreshed but never revived;
  * a second external id with the same business key links to the existing row
    instead of duplicating it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.database.tenancy import tenant_scope
from app.modules.currencies.model import Currency
from app.modules.organizations.model import Organization
from app.modules.sync.contract import SyncContract
from app.modules.sync.models import LinkState, SyncOutcome, SyncPayload, SyncRecord
from app.modules.tenants.model import Tenant
from app.modules.zoho.sync.config import (
    FieldMapping,
    SyncDirection,
    SyncStrategyName,
    resolve_module_config,
)
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.registry import ZohoModuleDefinition, sync_registry
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

MODULE = "xw_currencies"
ENDPOINT = "/settings/xw_currencies"      # distinct: one endpoint, one module

PAYLOAD = {
    "currency_id": "460000000000097",
    "currency_code": "USD",
    "currency_name": "US Dollar",
    "currency_symbol": "$",
    "price_precision": 2,
    "custom_fields": [{"api_name": "cf_desk", "value": "Treasury"}],
}


def _config(**overrides):
    return resolve_module_config(
        module=MODULE,
        endpoint=ENDPOINT,
        zoho_id_attr="currency_id",
        paginated=False,
        strategy=SyncStrategyName.FULL,
        direction=SyncDirection.INBOUND,
        detail_required=False,
        modified_since_param=None,
        sort_column=None,
        field_map=[
            FieldMapping(zoho="currency_code", local="currency_code"),
            FieldMapping(zoho="currency_name", local="currency_name"),
            FieldMapping(zoho="currency_symbol", local="currency_symbol"),
            FieldMapping(zoho="price_precision", local="price_precision", transform="int"),
        ],
        contract=SyncContract(
            source_system="zoho",
            entity_table="currency.currencies",
            match_on=("currency_code",),
            crosswalk=True,
            history_raw=True,
        ),
        **overrides,
    )


@pytest.fixture
async def world(db):
    """A tenant with one organization — ``currencies.organization_id`` is NOT NULL."""
    tenant = Tenant(tenant_code="XWALK", name="Crosswalk Ltd",
                    primary_contact_email="ops@xwalk.example", status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code="XWALK-HQ", legal_name="Crosswalk HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


@pytest.fixture
def crosswalk_spec(world):
    """Register the throwaway module, and take it back out again.

    The registry is a process-wide singleton whose validate() runs over every
    spec, so a test module left behind would be validated in every later test.
    """
    _, org = world

    def stamp_owner(payload: dict, values: dict) -> dict:
        # What a real adapter's pre_upsert does: resolve the owning org and
        # stamp the provenance pair the entity table requires.
        return {**values, "owner_type": "organization", "owner_id": org.id}

    spec = ZohoModuleDefinition(config=_config(), model=Currency, pre_upsert=stamp_owner)
    sync_registry.register(spec)
    sync_registry.validate()
    yield spec
    sync_registry._modules.pop(MODULE, None)   # noqa: SLF001 — no public unregister


def _client(records: list[dict]) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub("GET", ENDPOINT, make_response(records))
    return client


async def _run(db, world, records: list[dict]):
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        engine = ZohoSyncEngine(db, _client(records))
        report = await engine.run(MODULE, "full")
    await db.commit()
    return report


async def _counts(db) -> tuple[int, int, int]:
    """(entity rows, crosswalk rows, history rows).

    Entities are counted **including soft-deleted ones**: the question these
    assertions ask is "did a duplicate row appear", and the automatic
    soft-delete filter would answer it by hiding the very row under test.
    """
    currencies = await db.scalar(
        select(func.count()).select_from(Currency).execution_options(include_deleted=True)
    )
    records = await db.scalar(select(func.count()).select_from(SyncRecord))
    payloads = await db.scalar(select(func.count()).select_from(SyncPayload))
    return currencies, records, payloads


async def _live_currencies(db) -> int:
    return await db.scalar(select(func.count()).select_from(Currency))


# ── the shape ───────────────────────────────────────────────────────────────

async def test_a_first_sync_writes_entity_crosswalk_and_history(db, world, crosswalk_spec):
    report = await _run(db, world, [PAYLOAD])
    assert (report.status, report.created, report.errors) == ("success", 1, 0)

    currency = await db.scalar(select(Currency))
    assert (currency.currency_code, currency.currency_name) == ("USD", "US Dollar")
    assert currency.price_precision == 2

    record = await db.scalar(select(SyncRecord))
    assert record.external_id == PAYLOAD["currency_id"]
    assert record.module == MODULE and record.source_system == "zoho"
    assert record.entity_table == "currency.currencies"
    assert record.entity_id == currency.id, "the crosswalk must be linked after the flush"
    assert record.link_state == LinkState.LINKED
    assert record.tenant_id == currency.tenant_id
    assert record.organization_id == currency.organization_id
    assert record.raw == PAYLOAD and record.raw_hash is not None
    assert record.custom_fields == {"cf_desk": "Treasury"}
    assert record.sync_version == 1

    history = await db.scalar(select(SyncPayload))
    assert history.outcome == SyncOutcome.INSERTED
    assert history.sync_record_id == record.id and history.entity_id == currency.id
    assert history.raw == PAYLOAD


async def test_the_entity_table_carries_no_sync_columns(db, world, crosswalk_spec):
    await _run(db, world, [PAYLOAD])
    stored = set(Currency.__table__.columns.keys())
    assert not {"zoho_raw", "zoho_raw_hash", "sync_version", "remote_deleted_at"} & stored
    # The identity is the crosswalk's, not the entity's: nothing wrote the echo.
    currency = await db.scalar(select(Currency))
    assert currency.zoho_id is None


# ── idempotency ─────────────────────────────────────────────────────────────

async def test_an_unchanged_resync_writes_no_history(db, world, crosswalk_spec):
    await _run(db, world, [PAYLOAD])
    before = await _counts(db)

    report = await _run(db, world, [PAYLOAD])

    assert report.unchanged == 1 and report.created == 0 and report.updated == 0
    assert await _counts(db) == before, (
        "an unchanged scan must not append history — that is what makes a daily "
        "full sync of a large module free"
    )
    record = await db.scalar(select(SyncRecord))
    assert record.sync_version == 1, "a no-op must not burn a version"


async def test_a_changed_payload_updates_in_place_and_appends_one_history_row(db, world, crosswalk_spec):
    await _run(db, world, [PAYLOAD])
    report = await _run(db, world, [{**PAYLOAD, "currency_name": "United States Dollar"}])

    assert report.updated == 1
    currencies, records, payloads = await _counts(db)
    assert (currencies, records, payloads) == (1, 1, 2), "one entity, one crosswalk, two history rows"

    currency = await db.scalar(select(Currency))
    assert currency.currency_name == "United States Dollar"
    record = await db.scalar(select(SyncRecord))
    assert record.sync_version == 2
    latest = await db.scalar(select(SyncPayload).order_by(SyncPayload.sync_version.desc()))
    assert latest.outcome == SyncOutcome.UPDATED
    assert latest.changed_fields == ["currency_name"]


# ── the rules a naive split would break ─────────────────────────────────────

async def test_a_locally_deleted_row_is_reused_and_refreshed_but_never_revived(db, world, crosswalk_spec):
    """Three things at once, and the first is the one that actually breaks.

    The soft-deleted entity must still be FOUND — the automatic soft-delete
    filter would hide it, the engine would take it for a new record, and the
    unique index on (tenant, currency_code) would either fail the sync or, on a
    table without one, silently duplicate the row. Then it must be refreshed,
    and it must stay deleted: a sync tombstone is revived by newer evidence, a
    user's delete never is.
    """
    await _run(db, world, [PAYLOAD])
    currency = await db.scalar(select(Currency))
    deleted_id = currency.id
    currency.deleted_at = datetime.now(UTC)
    await db.commit()

    report = await _run(db, world, [{**PAYLOAD, "currency_name": "Dollar (US)"}])
    assert report.updated == 1

    currencies, records, _ = await _counts(db)
    assert (currencies, records) == (1, 1), "the deleted row was not reused — a duplicate appeared"
    assert await _live_currencies(db) == 0, "the row came back to life"

    refreshed = await db.scalar(
        select(Currency).execution_options(include_deleted=True)
    )
    assert refreshed.id == deleted_id
    assert refreshed.currency_name == "Dollar (US)", "a deleted row still takes updates"
    assert refreshed.deleted_at is not None, (
        "a user's delete is not the sync's to undo — the row was revived"
    )


async def test_a_second_external_id_with_the_same_business_key_links_instead_of_duplicating(
    db, world, crosswalk_spec
):
    """``match_on`` is how a second source finds the row the first one mastered."""
    await _run(db, world, [PAYLOAD])
    currency_id = (await db.scalar(select(Currency))).id

    await _run(db, world, [{**PAYLOAD, "currency_id": "999000111", "currency_name": "US Dollar"}])

    currencies, records, _ = await _counts(db)
    assert currencies == 1, "the business key matched: no duplicate canonical row"
    assert records == 2, "each source id still gets its own crosswalk row"
    linked = (await db.scalars(select(SyncRecord.entity_id))).all()
    assert set(linked) == {currency_id}


async def test_a_stale_payload_is_ignored_by_the_gate(db, world, crosswalk_spec):
    """Dated payloads keep the monotonic fence — older evidence never applies."""
    now = datetime.now(UTC).replace(microsecond=0)
    newer = {**PAYLOAD, "last_modified_time": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "currency_name": "Newer"}
    older = {**PAYLOAD, "currency_name": "Older",
             "last_modified_time": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S%z")}

    await _run(db, world, [newer])
    report = await _run(db, world, [older])

    assert report.stale_ignored == 1 and report.updated == 0
    currency = await db.scalar(select(Currency))
    assert currency.currency_name == "Newer"
    _, _, payloads = await _counts(db)
    assert payloads == 1, "a stale payload appends no history"
