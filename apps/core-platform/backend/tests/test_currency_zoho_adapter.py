"""The currency adapter end to end: sync in, guard edits, build payloads out.

Deliberately service-level rather than HTTP, so it exercises the rules without
the API fixtures (and stays runnable when Redis is not up).
"""

import pytest
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.modules.currencies import service
from app.modules.currencies.model import Currency, ExchangeRate
from app.modules.currencies.schema import CurrencyUpdate
from app.modules.currencies.scope import CurrencyRuleError
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.sync.translation import TranslationError
from app.modules.tenants.model import Tenant
from app.modules.zoho.sync.engine import ZohoSyncEngine
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

PAYLOAD = {
    "currency_id": "982000000004012",
    "currency_code": "AUD",
    "currency_name": "AUD- Australian Dollar",
    "currency_symbol": "$",
    "price_precision": 2,
    "currency_format": "1,234,567.89",
    "is_base_currency": False,
    "exchange_rate": "1.25",
    "effective_date": "2026-09-01",
}


@pytest.fixture
async def world(db):
    tenant = Tenant(tenant_code="CURADP", name="Adapter Ltd",
                    primary_contact_email="ops@curadp.example", status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code="CURADP-HQ", legal_name="Adapter HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


def _client(records: list[dict]) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub("GET", "/settings/currencies", make_response(records))
    return client


async def _sync(db, world, records=None):
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        report = await ZohoSyncEngine(db, _client(records or [PAYLOAD])).run("currencies", "full")
    await db.commit()
    return report


# ── inbound ─────────────────────────────────────────────────────────────────

async def test_a_sync_fills_the_canonical_row_and_its_rate_history(db, world):
    report = await _sync(db, world)
    assert report.created == 1 and report.errors == 0

    currency = await db.scalar(select(Currency))
    assert currency.currency_code == "AUD"
    assert currency.currency_name == "AUD- Australian Dollar"

    rate = await db.scalar(select(ExchangeRate))
    assert str(rate.rate) == "1.250000" and rate.rate_source == "zoho"
    assert rate.external_source == "zoho"
    assert rate.organization_id == currency.organization_id


async def test_a_restated_rate_updates_the_same_dated_row(db, world):
    await _sync(db, world)
    await _sync(db, world, [{**PAYLOAD, "exchange_rate": "1.40"}])

    rates = (await db.scalars(select(ExchangeRate))).all()
    assert len(rates) == 1, "the same (currency, date, source) is one row, restated"
    assert str(rates[0].rate) == "1.400000"


async def test_a_sync_without_an_organization_refuses_instead_of_guessing(db, world):
    """Which organization a tenant-wide Zoho setting belongs to is an open
    decision; the adapter must not quietly invent one."""
    tenant, _ = world
    with tenant_scope(tenant.id):                     # tenant, but no organization
        report = await ZohoSyncEngine(db, _client([PAYLOAD])).run("currencies", "full")
    await db.rollback()
    assert report.errors == 1 and report.created == 0


# ── the owned-field guard ───────────────────────────────────────────────────

async def test_a_zoho_owned_field_cannot_be_edited_on_a_linked_row(db, world):
    """The edit would save, then vanish on the next sync. Refuse it instead."""
    await _sync(db, world)
    tenant, org = world
    currency = await db.scalar(select(Currency))

    with tenant_scope(tenant.id, org.id), pytest.raises(CurrencyRuleError) as excinfo:
        await service.update_currency(
            db, str(currency.uuid),
            CurrencyUpdate(currency_name="My Dollar", row_version=currency.row_version),
        )
    assert "currency_name" in str(excinfo.value)
    assert excinfo.value.status_code == 422


async def test_a_field_zoho_does_not_feed_is_still_editable(db, world):
    await _sync(db, world)
    tenant, org = world
    currency = await db.scalar(select(Currency))

    with tenant_scope(tenant.id, org.id):
        updated = await service.update_currency(
            db, str(currency.uuid),
            CurrencyUpdate(gl_account_code="4000", row_version=currency.row_version),
        )
    assert updated.gl_account_code == "4000"


async def test_an_unlinked_currency_has_no_owned_fields(db, world):
    """The guard is about a live link, not about the column names."""
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        currency = Currency(currency_code="XAU", currency_name="Gold", owner_type="organization",
                            owner_id=org.id, organization_id=org.id, tenant_id=tenant.id)
        db.add(currency)
        await db.flush()
        updated = await service.update_currency(
            db, str(currency.uuid),
            CurrencyUpdate(currency_name="Gold Ounce", row_version=currency.row_version),
        )
    assert updated.currency_name == "Gold Ounce"


async def test_sources_for_reads_the_crosswalk(db, world):
    await _sync(db, world)
    currency = await db.scalar(select(Currency))
    links = await service.sources_for(db, currency)

    record = await db.scalar(select(SyncRecord))
    assert links == [{"source_system": "zoho", "module": "currencies",
                      "external_id": record.external_id, "link_state": "linked"}]


# ── outbound ────────────────────────────────────────────────────────────────

async def test_a_locally_created_currency_becomes_a_zoho_create_body(db, world):
    """'If I create a currency in my application, a proper Zoho payload is built.'"""
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        currency = Currency(currency_code="SGD", currency_symbol="S$", price_precision=2,
                            currency_format="1,234,567.89", currency_name="Local name",
                            owner_type="organization", owner_id=org.id,
                            organization_id=org.id, tenant_id=tenant.id)
        db.add(currency)
        await db.flush()

    body = service.to_zoho_payload(currency, create=True)
    assert body == {"currency_code": "SGD", "currency_symbol": "S$",
                    "price_precision": 2, "currency_format": "1,234,567.89"}
    assert "currency_name" not in body, "Zoho computes the name; sending ours is meaningless"


async def test_an_incomplete_currency_is_refused_before_the_api_call(db, world):
    tenant, org = world
    with tenant_scope(tenant.id, org.id):
        currency = Currency(currency_code="SGD", owner_type="organization", owner_id=org.id,
                            organization_id=org.id, tenant_id=tenant.id)
        db.add(currency)
        await db.flush()

    with pytest.raises(TranslationError) as excinfo:
        service.to_zoho_payload(currency, create=True)
    assert "currency_format" in str(excinfo.value)
