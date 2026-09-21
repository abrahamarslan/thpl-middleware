"""The orchestration: caching, the fallback chain, provenance and spend.

Upstreams are faked at ``transport.execute`` — the one seam between "what to
call" and "call it". Everything below that line (cache lookup, the audit row,
the licence window, parsing, fall-through) is the real code.
"""

from typing import ClassVar

import pytest
from sqlalchemy import func, select

from app.core.conf import settings
from app.database.tenancy import tenant_scope
from app.modules.geo.enums import GeoApiType, VerificationStatus
from app.modules.geo.geocoding import cache, registry, service, transport
from app.modules.geo.geocoding.base import GeocodingProvider
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeocodingUnavailable,
    GeoQuery,
    ProviderRejected,
    ProviderRequest,
    ProviderTransientError,
    ReverseQuery,
)
from app.modules.geo.model import GeocodeApiCall, Place
from app.modules.organizations.model import Organization
from app.modules.tenants.model import Tenant

PUNE = (18.5204, 73.8567)


class FakeProvider(GeocodingProvider):
    """A provider that answers from a canned payload, with a call counter."""

    name: ClassVar[str] = "fake"
    label: ClassVar[str] = "Fake"
    requires: ClassVar[tuple[str, ...]] = ()
    cost_per_call: ClassVar[float] = 2.5
    cache_days: ClassVar[int | None] = 7

    def build_forward(self, query: GeoQuery) -> ProviderRequest:
        return ProviderRequest(url="https://fake.test/search",
                               params={"q": query.text, "key": "SECRET"},
                               cache_params={"q": query.text})

    def build_reverse(self, query: ReverseQuery) -> ProviderRequest:
        return ProviderRequest(url="https://fake.test/reverse",
                               cache_params={"point": f"{query.latitude},{query.longitude}"})

    def parse(self, payload, api_type) -> list[GeocodeResult]:
        return [
            GeocodeResult(
                provider=self.name, latitude=item["lat"], longitude=item["lng"],
                formatted_address=item.get("label"),
                provider_place_id=item.get("id"),
                components=item.get("components", {}),
                confidence=0.9,
            )
            for item in (payload or {}).get("hits", [])
        ]


class SecondProvider(FakeProvider):
    name: ClassVar[str] = "second"
    label: ClassVar[str] = "Second"
    cost_per_call: ClassVar[float] = 1.0


PAYLOAD = {"hits": [{
    "lat": PUNE[0], "lng": PUNE[1], "id": "fake-1",
    "label": "12 Mahatma Gandhi Road, Pune, Maharashtra 411001, India",
    "components": {"street": "12 Mahatma Gandhi Road", "city": "Pune",
                   "state": "Maharashtra", "postal_code": "411001",
                   "country": "India", "country_code": "IN"},
}]}
EMPTY = {"hits": []}


@pytest.fixture
def providers(monkeypatch):
    registry.register_geocoder(FakeProvider)
    registry.register_geocoder(SecondProvider)
    monkeypatch.setattr(settings, "GEOCODING_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "GEOCODING_PROVIDER", "fake", raising=False)
    monkeypatch.setattr(settings, "GEOCODING_FALLBACK_PROVIDERS", "", raising=False)
    return settings


@pytest.fixture
def calls(monkeypatch):
    """Replace HTTP with a scripted queue; record what was attempted."""
    log: list[str] = []
    script: dict[str, object] = {}

    async def fake_execute(request, *, provider, rate_limit):
        log.append(provider)
        outcome = script.get(provider, PAYLOAD)
        if isinstance(outcome, Exception):
            raise outcome
        return transport.CallOutcome(payload=outcome, http_status=200, latency_ms=12, attempts=1)

    monkeypatch.setattr(transport, "execute", fake_execute)
    return type("Calls", (), {"log": log, "script": script})()


async def _world(db, code: str = "GEOC"):
    tenant = Tenant(tenant_code=code, name=f"{code} Ltd", primary_contact_email=f"ops@{code.lower()}.test")
    db.add(tenant)
    await db.flush()
    with tenant_scope(tenant.id):
        org = Organization(org_code=f"{code}-HQ", legal_name=f"{code} HQ", tenant_id=tenant.id)
        db.add(org)
        await db.flush()
    return tenant, org


# ── the happy path and the cache ────────────────────────────────────────────

async def test_a_geocode_is_recorded_with_its_cost_and_provenance(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))

        assert outcome.provider == "fake" and outcome.cached is False
        assert outcome.best.components["city"] == "Pune"

        call = await db.get(GeocodeApiCall, outcome.call_id)
        assert call.provider == "fake"
        assert call.api_type == GeoApiType.FORWARD_GEOCODE.value
        assert call.cost_units == pytest.approx(2.5)        # spend ledger
        assert call.http_status == 200 and call.latency_ms == 12
        assert call.response_raw == PAYLOAD                 # the audit trail
        assert call.expires_at is not None                  # the licence window


async def test_the_second_identical_call_never_reaches_the_provider(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
        second = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))

    assert calls.log == ["fake"]                            # one upstream call, two answers
    assert first.cached is False and second.cached is True
    assert second.call_id == first.call_id
    assert second.best.latitude == pytest.approx(first.best.latitude)


async def test_the_cache_key_ignores_whitespace_and_case(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
        # Normalization happens in GeoQuery, so these are the same request.
        assert GeoQuery(text="  12   mg ROAD, Pune ").normalized() == \
               GeoQuery(text="12 MG Road, Pune").normalized()


async def test_reverse_geocoding_rounds_the_point_so_the_cache_can_warm(db, providers, calls):
    """Two fixes from the same doorway must not be two cache entries."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        await service.reverse_geocode(db, ReverseQuery(18.52041, 73.85672))
        again = await service.reverse_geocode(db, ReverseQuery(18.520409, 73.856718))
    assert calls.log == ["fake"] and again.cached is True


async def test_an_api_key_is_never_written_to_the_audit_table(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
        call = await db.get(GeocodeApiCall, outcome.call_id)
    assert "SECRET" not in str(call.request_params)
    assert "key" not in call.request_params


# ── the fallback chain ──────────────────────────────────────────────────────

async def test_a_failing_provider_falls_through_to_the_next(db, providers, calls, monkeypatch):
    monkeypatch.setattr(settings, "GEOCODING_FALLBACK_PROVIDERS", "second", raising=False)
    calls.script["fake"] = ProviderTransientError("fake: timeout")
    tenant, org = await _world(db)

    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))

    assert calls.log == ["fake", "second"]
    assert outcome.provider == "second" and outcome.best is not None
    assert "fake" in outcome.errors
    assert outcome.providers_tried == ["fake", "second"]


async def test_an_empty_answer_also_falls_through(db, providers, calls, monkeypatch):
    """Coverage differs by provider; an empty result is worth a second opinion."""
    monkeypatch.setattr(settings, "GEOCODING_FALLBACK_PROVIDERS", "second", raising=False)
    calls.script["fake"] = EMPTY
    tenant, org = await _world(db)

    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
        assert outcome.provider == "second"
        # The empty answer is cached too, so the retry skips straight past it.
        calls.log.clear()
        await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
    assert calls.log == []


async def test_a_failed_call_is_audited_but_never_served(db, providers, calls):
    tenant, org = await _world(db)
    calls.script["fake"] = ProviderRejected("fake: HTTP 403")

    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
        assert outcome.results == [] and "fake" in outcome.errors

        recorded = await db.scalar(select(func.count()).select_from(GeocodeApiCall))
        assert recorded == 1                                # it is in the audit trail
        digest = cache.request_hash("fake", GeoApiType.FORWARD_GEOCODE, {"q": "12 MG Road, Pune"})
        assert await cache.lookup(
            db, provider="fake", api_type=GeoApiType.FORWARD_GEOCODE, digest=digest,
        ) is None                                           # but never servable


async def test_all_providers_failing_yields_no_results_not_an_exception(db, providers, calls):
    tenant, org = await _world(db)
    calls.script["fake"] = ProviderTransientError("down")
    with tenant_scope(tenant.id, org.id):
        outcome = await service.geocode(db, GeoQuery(text="nowhere"))
    assert outcome.results == [] and outcome.provider is None


async def test_geocoding_disabled_is_a_clear_refusal(db, monkeypatch):
    monkeypatch.setattr(settings, "GEOCODING_ENABLED", False, raising=False)
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id), pytest.raises(GeocodingUnavailable, match="disabled"):
        await service.geocode(db, GeoQuery(text="Pune"))


async def test_no_provider_configured_is_a_clear_refusal(db, providers, monkeypatch):
    monkeypatch.setattr(settings, "GEOCODING_PROVIDER", "", raising=False)
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id), pytest.raises(GeocodingUnavailable, match="No geocoding provider"):
        await service.geocode(db, GeoQuery(text="Pune"))


# ── tenancy ─────────────────────────────────────────────────────────────────

async def test_one_tenants_cache_never_answers_anothers_lookup(db, providers, calls):
    """A request hash contains the address someone searched for."""
    acme_tenant, acme_org = await _world(db, "ACMEG")
    globex_tenant, globex_org = await _world(db, "GLOBEXG")

    with tenant_scope(acme_tenant.id, acme_org.id):
        await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))
    with tenant_scope(globex_tenant.id, globex_org.id):
        outcome = await service.geocode(db, GeoQuery(text="12 MG Road, Pune"))

    assert calls.log == ["fake", "fake"]                    # both paid
    assert outcome.cached is False


# ── applying to a place ─────────────────────────────────────────────────────

async def test_geocoding_a_place_fills_coordinates_and_provenance(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = Place(kind="address", street="12 MG Road", city="Pune",
                      postal_code="411001", country="India", organization_id=org.id)
        db.add(place)
        await db.flush()

        place, outcome = await service.geocode_place(db, place)
        await db.commit()
        await db.refresh(place)

    assert float(place.latitude) == pytest.approx(PUNE[0], abs=1e-6)
    assert place.provider == "fake" and place.provider_place_id == "fake-1"
    assert place.geocode_call_id == outcome.call_id and place.geocoded_at is not None
    # A machine's opinion is not verification.
    assert place.verification_status == VerificationStatus.GEOCODED_ONLY.value
    assert place.is_verified is False


async def test_a_zoho_place_keeps_the_address_zoho_owns(db, providers, calls):
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        place = Place(kind="warehouse", zoho_id="46000123", location_name="Head Office",
                      street="5 Industrial Estate", city="Pune", country="India",
                      organization_id=org.id)
        db.add(place)
        await db.flush()

        place, _ = await service.geocode_place(db, place)

    assert float(place.latitude) == pytest.approx(PUNE[0], abs=1e-6)   # position: taken
    assert place.street == "5 Industrial Estate"                       # address: untouched
    assert place.city == "Pune"


async def test_two_places_cannot_claim_the_same_provider_id(db, providers, calls):
    """``uq_places_provider_place_live`` would reject the second write."""
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        first = Place(kind="address", street="12 MG Road", city="Pune",
                      country="India", organization_id=org.id)
        second = Place(kind="address", street="12 Mahatma Gandhi Rd", city="Pune",
                       country="India", organization_id=org.id)
        db.add_all([first, second])
        await db.flush()

        first, _ = await service.geocode_place(db, first)
        second, _ = await service.geocode_place(db, second)
        await db.commit()

    assert first.provider_place_id == "fake-1"
    assert second.provider_place_id is None            # conceded, not crashed
    assert float(second.latitude) == pytest.approx(PUNE[0], abs=1e-6)


# ── routing ─────────────────────────────────────────────────────────────────

async def test_without_a_routing_provider_distance_is_a_straight_line(db, monkeypatch):
    monkeypatch.setattr(settings, "ROUTING_PROVIDER", "", raising=False)
    tenant, org = await _world(db)
    with tenant_scope(tenant.id, org.id):
        leg = await service.distance_between(db, PUNE, (19.0760, 72.8777))

    assert leg.provider == "haversine"
    assert leg.distance_m == pytest.approx(118_000, rel=0.05)
    # Never a travel time nobody measured.
    assert leg.duration_s is None
