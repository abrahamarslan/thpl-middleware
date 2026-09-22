"""Currency module: the canonical master, strict org scoping, and the
effective-dated exchange-rate history (cache vs truth).

Unit tests are hermetic; integration tests use the ``worlds`` fixture (two
tenants with users) and the migrated scratch database.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.common.exception.errors import NotFoundError
from app.database.tenancy import tenant_scope
from app.modules.currencies import service
from app.modules.currencies.enums import CurrencyKind, values
from app.modules.currencies.model import Currency
from app.modules.currencies.schema import CurrencyCreate, ExchangeRateIn
from app.modules.currencies.scope import CurrencyRuleError, require_organization
from app.modules.organizations.model import Organization


async def _org(db, world) -> Organization:
    """The world's organization — currency rows require one.

    ``worlds`` builds it now (users are organization-scoped, so every world has
    an HQ); creating a second one here would collide on
    ``uq_organizations_code_active``.
    """
    return world.organization


def _currency(**kw) -> dict:
    return {"currency_code": "INR", "currency_name": "Indian Rupee", "currency_symbol": "₹", **kw}


# ── unit: vocabulary and schema validation ──────────────────────────────────

def test_the_vocabularies_are_closed_sets():
    assert values(CurrencyKind) == "'fiat','crypto','metals','historical'"


def test_request_schemas_validate_the_obvious_mistakes():
    with pytest.raises(ValidationError):
        CurrencyCreate(currency_code="RUPEE")
    with pytest.raises(ValidationError):
        CurrencyCreate(currency_code="IN")
    with pytest.raises(ValidationError):
        ExchangeRateIn(rate=Decimal("-1"), effective_date=date(2026, 1, 1))


# ── integration: the master ─────────────────────────────────────────────────

async def test_create_read_and_list_a_currency(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)

    created = await client.post("/api/currencies", json=_currency(is_base_currency=True),
                                headers=acme.auth(acme.member))
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["currency_code"] == "INR" and data["is_base_currency"] is True
    assert data["status"] == "active" and data["is_verified"] is False
    assert data["row_version"] == 1 and data["created_by_name"] == acme.member.name
    assert data["organization_id"]

    by_uuid = await client.get(f"/api/currencies/{data['id']}", headers=acme.auth(acme.member))
    assert by_uuid.json()["data"]["currency_code"] == "INR"
    by_code = await client.get("/api/currencies/INR", headers=acme.auth(acme.member))
    assert by_code.json()["data"]["id"] == data["id"]

    listed = await client.get("/api/currencies", headers=acme.auth(acme.member))
    assert [c["currency_code"] for c in listed.json()["data"]] == ["INR"]


async def test_exactly_one_base_currency_per_organization(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    headers = acme.auth(acme.member)

    await client.post("/api/currencies", json=_currency(is_base_currency=True), headers=headers)
    await client.post("/api/currencies", json={"currency_code": "USD", "currency_name": "US Dollar",
                                               "is_base_currency": True}, headers=headers)

    base = await client.get("/api/currencies", params={"base_only": True}, headers=headers)
    assert [c["currency_code"] for c in base.json()["data"]] == ["USD"]
    inr = await client.get("/api/currencies/INR", headers=headers)
    assert inr.json()["data"]["is_base_currency"] is False


async def test_a_duplicate_code_is_a_conflict(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    headers = acme.auth(acme.member)
    assert (await client.post("/api/currencies", json=_currency(), headers=headers)).status_code == 201
    again = await client.post("/api/currencies", json=_currency(currency_name="Rupee again"), headers=headers)
    assert again.status_code == 409


async def test_a_stale_row_version_is_a_409(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    headers = acme.auth(acme.member)
    data = (await client.post("/api/currencies", json=_currency(), headers=headers)).json()["data"]

    ok = await client.patch(f"/api/currencies/{data['id']}",
                            json={"currency_name": "Rupee renamed", "row_version": data["row_version"]},
                            headers=headers)
    assert ok.status_code == 200 and ok.json()["data"]["row_version"] == 2

    stale = await client.patch(f"/api/currencies/{data['id']}",
                               json={"currency_name": "Again", "row_version": data["row_version"]},
                               headers=headers)
    assert stale.status_code == 409
    assert stale.json()["data"]["current_row_version"] == 2


async def test_verification_needs_a_tenant_admin(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    data = (await client.post("/api/currencies", json=_currency(),
                              headers=acme.auth(acme.member))).json()["data"]
    url = f"/api/currencies/{data['id']}/verify"

    denied = await client.post(url, json={"verification_method": "manual_review"}, headers=acme.auth(acme.member))
    assert denied.status_code == 403

    verified = await client.post(url, json={"verification_method": "manual_review"}, headers=acme.auth(acme.admin))
    assert verified.status_code == 200 and verified.json()["data"]["is_verified"] is True


# ── integration: exchange rates ─────────────────────────────────────────────

async def test_rates_supersede_and_refresh_the_cache(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    headers = acme.auth(acme.member)
    data = (await client.post("/api/currencies", json=_currency(), headers=headers)).json()["data"]
    ref = data["id"]

    assert (await client.post(f"/api/currencies/{ref}/rates",
                              json={"rate": "83.5", "effective_date": "2026-01-01", "rate_source": "rbi"},
                              headers=headers)).status_code == 201
    assert (await client.post(f"/api/currencies/{ref}/rates",
                              json={"rate": "84.0", "effective_date": "2026-02-01", "rate_source": "rbi"},
                              headers=headers)).status_code == 201

    rates = (await client.get(f"/api/currencies/{ref}/rates", headers=headers)).json()["data"]
    assert [r["effective_date"] for r in rates] == ["2026-02-01", "2026-01-01"]
    assert [r["status"] for r in rates] == ["active", "superseded"]

    currency = (await client.get(f"/api/currencies/{ref}", headers=headers)).json()["data"]
    assert Decimal(currency["exchange_rate"]) == Decimal("84")
    assert currency["exchange_rate_source"] == "rbi"

    latest = (await client.get(f"/api/currencies/{ref}/rate", headers=headers)).json()["data"]
    assert Decimal(latest["rate"]) == Decimal("84")
    as_of = (await client.get(f"/api/currencies/{ref}/rate", params={"as_of": "2026-01-15"},
                              headers=headers)).json()["data"]
    assert Decimal(as_of["rate"]) == Decimal("83.5")

    # Re-posting the same business date from the SAME source updates that row
    # instead of colliding with uq_exchange_rates_currency_date.
    assert (await client.post(f"/api/currencies/{ref}/rates",
                              json={"rate": "84.25", "effective_date": "2026-02-01", "rate_source": "rbi"},
                              headers=headers)).status_code == 201
    rates = (await client.get(f"/api/currencies/{ref}/rates", headers=headers)).json()["data"]
    assert len(rates) == 2 and Decimal(rates[0]["rate"]) == Decimal("84.25")

    # A DIFFERENT source quoting the same day is a row of its own — that is why
    # rate_source is part of the uniqueness key — and it does not overwrite RBI.
    assert (await client.post(f"/api/currencies/{ref}/rates",
                              json={"rate": "84.90", "effective_date": "2026-02-01"},
                              headers=headers)).status_code == 201
    rates = (await client.get(f"/api/currencies/{ref}/rates", headers=headers)).json()["data"]
    same_day = {r["rate_source"]: Decimal(r["rate"]) for r in rates if r["effective_date"] == "2026-02-01"}
    assert same_day == {"rbi": Decimal("84.25"), "manual": Decimal("84.90")}


async def test_a_currency_in_use_is_archived_not_deleted(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    headers = acme.auth(acme.member)
    data = (await client.post("/api/currencies", json=_currency(), headers=headers)).json()["data"]
    ref = data["id"]
    await client.post(f"/api/currencies/{ref}/rates",
                      json={"rate": "83.5", "effective_date": "2026-01-01"}, headers=headers)

    refused = await client.delete(f"/api/currencies/{ref}", params={"reason": "cleanup"},
                                  headers=acme.auth(acme.admin))
    assert refused.status_code == 422 and refused.json()["code"] == "currency_rule_violation"

    archived = await client.post(f"/api/currencies/{ref}/archive", params={"reason": "retired"},
                                 headers=acme.auth(acme.admin))
    assert archived.json()["data"]["status"] == "archived"


async def test_one_tenant_never_sees_anothers_currency(worlds, db):
    client, acme, globex = worlds
    await _org(db, acme)
    await _org(db, globex)
    data = (await client.post("/api/currencies", json=_currency(),
                              headers=acme.auth(acme.member))).json()["data"]

    assert (await client.get(f"/api/currencies/{data['id']}",
                             headers=globex.auth(globex.member))).status_code == 404
    listed = await client.get("/api/currencies", headers=globex.auth(globex.member))
    assert listed.json()["data"] == []


async def test_a_tenant_without_an_organization_is_told_so(db):
    """The guard is no longer reachable through the API — a signed-in user always
    has an organization (``users.organization_id`` is NOT NULL) — but a system
    context (Celery, a sync run) still binds a tenant with no organization."""
    from app.modules.tenants.model import Tenant

    bare = Tenant(tenant_code="BARE", name="Bare Ltd", primary_contact_email="ops@bare.example",
                  status="active")
    db.add(bare)
    await db.flush()

    with tenant_scope(bare.id):
        with pytest.raises(CurrencyRuleError, match="no organization"):
            await require_organization(db)


# ── integration: the database guards ────────────────────────────────────────

async def test_the_database_keeps_one_live_code_per_tenant(worlds, db):
    client, acme, _ = worlds
    await _org(db, acme)
    data = (await client.post("/api/currencies", json=_currency(),
                              headers=acme.auth(acme.member))).json()["data"]

    row = await db.scalar(select(Currency).where(Currency.uuid == data["id"]))
    with pytest.raises(IntegrityError, match="uq_currencies_tenant_code"):
        await db.execute(text(
            "INSERT INTO currency.currencies "
            "(uuid, tenant_id, organization_id, currency_code, owner_type, owner_id) "
            "VALUES (:uuid, :t, :o, 'INR', 'organization', :o)"
        ), {"uuid": str(uuid4()), "t": row.tenant_id, "o": row.organization_id})


async def test_service_requires_an_organization_and_hides_unknowns(db):
    with pytest.raises(NotFoundError):
        await service.get_currency(db, "NOPE")
    # No tenant/organization context and no organizations exist: a usable 422,
    # not a raw IntegrityError from the NOT NULL organization_id.
    with pytest.raises(CurrencyRuleError):
        await service.create_currency(db, CurrencyCreate(currency_code="INR", currency_name="Indian Rupee"))