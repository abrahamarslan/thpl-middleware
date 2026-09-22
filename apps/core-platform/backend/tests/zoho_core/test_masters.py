"""O1 masters: currencies (non-paginated list) and taxes (paginated), end to end."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database.tenancy import tenant_scope
from app.main import app
from app.modules.currencies.model import Currency, ExchangeRate
from app.modules.organizations.model import Organization
from app.modules.sync.models import SyncRecord
from app.modules.taxes.model import TaxComponent
from app.modules.tenants.model import Tenant
from app.modules.users.deps import get_current_user
from app.modules.zoho.sync.engine import ZohoSyncEngine
from tests.zoho_sync.fake_client import FakeZohoClient, make_response

CURRENCIES = [
    {"currency_id": "982000000004012", "currency_code": "AUD", "currency_name": "AUD- Australian Dollar",
     "currency_symbol": "$", "price_precision": 2, "currency_format": "1,234,567.89",
     "is_base_currency": False, "exchange_rate": 54.12, "effective_date": "2026-09-01"},
    {"currency_id": "982000000004000", "currency_code": "INR", "currency_name": "INR- Indian Rupee",
     "currency_symbol": "₹", "price_precision": 2, "currency_format": "1,23,45,678.90",
     "is_base_currency": True, "exchange_rate": 1, "effective_date": "2013-09-04"},
]

TAXES = [
    {"tax_id": f"9820000005660{i:02d}", "tax_name": f"GST{rate}", "tax_percentage": rate, "tax_type": "tax",
     "tax_specific_type": kind, "is_value_added": False, "is_default_tax": i == 0, "is_editable": True}
    for i, (rate, kind) in enumerate([(18, "igst"), (9, "cgst"), (9, "sgst")])
]


def currencies_client() -> FakeZohoClient:
    client = FakeZohoClient()
    # One response, and — as documented — no pagination was requested.
    client.stub("GET", "/settings/currencies", make_response(CURRENCIES))
    return client


def taxes_client() -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/settings/taxes", [TAXES[:2], TAXES[2:]])
    return client


async def _tenant_org(db):
    """Currencies land in the canonical master, which requires an organization."""
    tenant = Tenant(tenant_code="MASTERS", name="Masters Ltd",
                    primary_contact_email="ops@masters.example", status="active")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code="MASTERS-HQ", legal_name="Masters HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    await db.commit()
    return tenant, org


async def test_currencies_pull_into_the_canonical_master_and_then_write_nothing(db):
    """Currencies is the first crosswalk module: no mirror table, no zoho_* columns."""
    tenant, org = await _tenant_org(db)
    client = currencies_client()
    with tenant_scope(tenant.id, org.id):
        report = await ZohoSyncEngine(db, client).run("currencies")
    await db.commit()

    assert report.created == 2 and report.pages == 1
    assert len(client.calls) == 1 and client.calls[0]["params"] is None      # not paginated

    inr = await db.scalar(select(Currency).where(Currency.currency_code == "INR"))
    assert inr.is_base_currency is True
    assert inr.currency_name == "INR- Indian Rupee"       # decoded, not recomputed

    # Identity lives in the crosswalk — the canonical row holds no source id.
    record = await db.scalar(
        select(SyncRecord).where(SyncRecord.external_id == "982000000004000")
    )
    assert record.entity_id == inr.id and record.entity_table == "currency.currencies"
    assert record.raw_source == "list:full" and record.raw_hash

    # The rate carried inline on the currency payload became history, and the
    # column on the currency row is only the cache of it.
    rate = await db.scalar(select(ExchangeRate).where(ExchangeRate.currency_id == inr.id))
    assert rate.rate_source == "zoho" and rate.effective_date.isoformat() == "2013-09-04"

    with tenant_scope(tenant.id, org.id):
        again = await ZohoSyncEngine(db, currencies_client()).run("currencies")
    await db.commit()
    assert again.unchanged == 2 and again.created == again.updated == 0


async def test_taxes_pull_across_pages(db):
    report = await ZohoSyncEngine(db, taxes_client()).run("taxes")
    await db.commit()
    assert report.pages == 2 and report.created == 3
    cgst = await db.scalar(select(TaxComponent).where(TaxComponent.tax_specific_type == "cgst"))
    assert str(cgst.tax_percentage) == "9.0000"


@pytest.fixture
async def api_client(db):
    import httpx

    from app.database.db import get_db

    async def _db():
        yield db

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, email="u@x.com")
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_read_endpoints_serve_the_canonical_masters(db, api_client):
    """The read endpoints moved with the data.

    ``/api/taxes`` and ``/api/currencies`` serve canonical masters; the
    ``/api/zoho/*`` mirror routes went with their tables.
    """
    tenant, org = await _tenant_org(db)
    with tenant_scope(tenant.id, org.id):
        await ZohoSyncEngine(db, taxes_client()).run("taxes")
    await db.commit()

    igst = (await api_client.get("/api/taxes", params={"specific_type": "igst"})).json()["data"]
    assert len(igst) == 1 and igst[0]["tax_name"] == "GST18"
    # The Zoho id is the crosswalk's, so it resolves the same row without an echo column.
    fat = (await api_client.get("/api/taxes/982000000566000")).json()["data"]
    assert fat["id"] == igst[0]["id"] and fat["tax_type"] == "tax"
    assert [(s["source_system"], s["module"], s["external_id"]) for s in fat["sources"]] == [
        ("zoho", "taxes", "982000000566000")]
    assert (await api_client.get("/api/taxes/nope")).status_code == 404
