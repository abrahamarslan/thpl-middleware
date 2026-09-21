"""O1 masters: currencies (non-paginated list) and taxes (paginated), end to end."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.main import app
from app.modules.zoho_currencies.model import ZohoCurrency
from app.modules.taxes.model import ZohoTax
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


async def test_currencies_pull_in_one_call_and_then_write_nothing(db):
    client = currencies_client()
    report = await ZohoSyncEngine(db, client).run("currencies")
    await db.commit()
    assert report.created == 2 and report.pages == 1
    assert len(client.calls) == 1 and client.calls[0]["params"] is None      # not paginated

    inr = await db.scalar(select(ZohoCurrency).where(ZohoCurrency.currency_code == "INR"))
    assert inr.is_base_currency is True and inr.zoho_id == "982000000004000"
    assert inr.sync_source == "list:full" and inr.zoho_raw_hash

    again = await ZohoSyncEngine(db, currencies_client()).run("currencies")
    await db.commit()
    assert again.unchanged == 2 and again.created == again.updated == 0


async def test_taxes_pull_across_pages(db):
    report = await ZohoSyncEngine(db, taxes_client()).run("taxes")
    await db.commit()
    assert report.pages == 2 and report.created == 3
    cgst = await db.scalar(select(ZohoTax).where(ZohoTax.tax_specific_type == "cgst"))
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


async def test_read_endpoints_serve_the_mirror(db, api_client):
    await ZohoSyncEngine(db, currencies_client()).run("currencies")
    await ZohoSyncEngine(db, taxes_client()).run("taxes")
    await db.commit()

    listed = (await api_client.get("/api/zoho/currencies")).json()["data"]
    assert [c["currency_code"] for c in listed][0] == "INR"                  # base currency first
    by_code = (await api_client.get("/api/zoho/currencies/inr")).json()["data"]
    assert by_code["zoho_id"] == "982000000004000"

    igst = (await api_client.get("/api/zoho/taxes", params={"specific_type": "igst"})).json()["data"]
    assert len(igst) == 1 and igst[0]["tax_name"] == "GST18"
    assert (await api_client.get("/api/zoho/taxes/nope")).status_code == 404
