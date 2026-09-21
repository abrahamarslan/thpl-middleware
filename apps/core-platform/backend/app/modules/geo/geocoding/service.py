"""Geocoding and routing, orchestrated.

One flow, applied to every provider in the chain:

    cache lookup  →  breaker / rate limit  →  HTTP with retries
                  →  record the call (cache + audit + spend)
                  →  parse  →  results, or fall through to the next provider

Providers never see any of it. That is the point: the twentieth provider gets
the same caching, resilience and audit trail as the first, for free, because
none of it is theirs to implement.

Falling through on an *empty* answer as well as on failure is deliberate.
Coverage differs by provider and by district — Nominatim often knows an
Indian address that Google returns ZERO_RESULTS for, and the empty answer is
still cached per provider so the fall-through costs nothing the second time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import structlog
from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.tenancy import current_actor
from app.modules.geo.distance import ensure_point
from app.modules.geo.enums import GeoApiType, VerificationStatus
from app.modules.geo.geocoding import cache, registry, transport
from app.modules.geo.geocoding.base import GeocodingProvider
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeocodingUnavailable,
    GeoQuery,
    ProviderRejected,
    ProviderRequest,
    ProviderTransientError,
    ReverseQuery,
    RouteLeg,
)
from app.modules.geo.model import Place, ZOHO_OWNED_PLACE_FIELDS
from app.modules.geo.scope import GeoRuleError, require_organization

logger = structlog.get_logger("app.geo.geocoding")


@dataclass(slots=True)
class GeocodeOutcome:
    """What happened, not just what was found — the API returns all of it so
    an operator can see whether a bill was incurred."""

    results: list[GeocodeResult] = field(default_factory=list)
    provider: str | None = None
    cached: bool = False
    call_id: int | None = None
    providers_tried: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def best(self) -> GeocodeResult | None:
        return self.results[0] if self.results else None


def _settings():
    from app.core.conf import settings

    return settings


def _rate_limit(provider: GeocodingProvider) -> int:
    configured = _settings().GEOCODING_MAX_CALLS_PER_MINUTE
    ceiling = provider.max_calls_per_minute
    # A provider's published policy is a ceiling, not a suggestion: never let
    # local configuration raise it.
    return min(configured, ceiling) if ceiling else configured


def _cache_days(provider: GeocodingProvider) -> int:
    return provider.cache_days if provider.cache_days is not None else _settings().GEOCODING_CACHE_DAYS


# ── the core loop ───────────────────────────────────────────────────────────

async def _run(
    db: AsyncSession, *, api_type: GeoApiType, build, identity: dict,
    provider_name: str | None = None,
) -> GeocodeOutcome:
    settings = _settings()
    if not settings.GEOCODING_ENABLED:
        raise GeocodingUnavailable(
            "Geocoding is disabled; set GEOCODING_ENABLED=true and GEOCODING_PROVIDER."
        )
    chain = ([registry.geocoder(provider_name)] if provider_name
             else registry.geocoder_chain(settings))
    if not chain:
        raise GeocodingUnavailable(
            "No geocoding provider is configured; see GET /api/geocoding/providers."
        )

    organization_id = await require_organization(db)
    actor_id = current_actor().user_id
    outcome = GeocodeOutcome()

    for provider in chain:
        outcome.providers_tried.append(provider.name)
        request: ProviderRequest = build(provider)
        # The cache key is the QUERY's identity, not the built request: the
        # query is where rounding and whitespace normalization live, and two
        # fixes from the same doorway must hit one entry or the cache never
        # warms. ``cache_params`` is still what gets STORED, for the audit trail.
        digest = cache.request_hash(
            provider.name, api_type, {"query": identity, "variant": provider.cache_variant},
        )

        hit = await cache.lookup(db, provider=provider.name, api_type=api_type, digest=digest)
        if hit is not None:
            results = provider.parse(hit.response_raw, api_type)
            logger.debug("geo.geocoding.cache_hit", provider=provider.name, call_id=hit.id)
            if results:
                return GeocodeOutcome(results, provider.name, True, hit.id,
                                      outcome.providers_tried, outcome.errors)
            continue                                    # cached empty → next provider

        try:
            call = await transport.execute(
                request, provider=provider.name, rate_limit=_rate_limit(provider),
            )
        except (ProviderTransientError, ProviderRejected) as exc:
            outcome.errors[provider.name] = str(exc)
            await cache.record(
                db, organization_id=organization_id, provider=provider.name, api_type=api_type,
                digest=digest, cache_params=request.cache_params,
                response_status=type(exc).__name__, servable=False,
                cost_units=provider.cost_per_call, requested_by=actor_id,
            )
            logger.warning("geo.geocoding.provider_failed", provider=provider.name, error=str(exc))
            continue

        status = provider.check_payload(call.payload)
        rejected = bool(status) and provider.is_rejection(status)
        results = [] if rejected else provider.parse(call.payload, api_type)

        recorded = await cache.record(
            db, organization_id=organization_id, provider=provider.name, api_type=api_type,
            digest=digest, cache_params=request.cache_params, payload=call.payload,
            response_status=status or "OK", http_status=call.http_status,
            latency_ms=call.latency_ms, cost_units=provider.cost_per_call,
            cache_days=_cache_days(provider), servable=not rejected, empty=not results,
            requested_by=actor_id,
        )

        if rejected:
            outcome.errors[provider.name] = f"provider status {status}"
            logger.error("geo.geocoding.provider_rejected", provider=provider.name, status=status)
            continue
        if results:
            return GeocodeOutcome(results, provider.name, False, recorded.id,
                                  outcome.providers_tried, outcome.errors)
        logger.info("geo.geocoding.no_results", provider=provider.name)

    return outcome                                      # tried everything, found nothing


async def geocode(
    db: AsyncSession, query: GeoQuery, *, provider: str | None = None,
) -> GeocodeOutcome:
    """Address text → coordinates."""
    if not (query.text or "").strip():
        raise GeoRuleError("Give an address to search for")
    return await _run(
        db, api_type=GeoApiType.FORWARD_GEOCODE,
        build=lambda p: p.build_forward(query), identity=query.normalized(),
        provider_name=provider,
    )


async def reverse_geocode(
    db: AsyncSession, query: ReverseQuery, *, provider: str | None = None,
) -> GeocodeOutcome:
    """Coordinates → address."""
    ensure_point(query.latitude, query.longitude)
    return await _run(
        db, api_type=GeoApiType.REVERSE_GEOCODE,
        build=lambda p: p.build_reverse(query), identity=query.normalized(),
        provider_name=provider,
    )


# ── applying a result to a place ────────────────────────────────────────────

def address_text(place: Place) -> str:
    """What to ask a provider about this place."""
    parts = [
        place.building_name, place.street, place.street2, place.sub_locality,
        place.locality, place.city, place.district, place.state, place.postal_code, place.country,
    ]
    text = ", ".join(p.strip() for p in parts if p and p.strip())
    return text or (place.formatted_address or place.location_name or "")


async def _provider_place_free(db: AsyncSession, place: Place, provider_place_id: str | None) -> bool:
    """``uq_places_provider_place_live`` allows one place per provider id."""
    if not provider_place_id:
        return False
    taken = await db.scalar(
        select(Place.id).where(
            Place.provider_place_id == provider_place_id, Place.id != place.id,
        ).limit(1)
    )
    if taken:
        # Worth knowing about: two of our places are the same doorway to the
        # provider. Not worth failing the geocode over.
        logger.info("geo.geocoding.duplicate_provider_place",
                    place_id=place.id, other_place_id=taken, provider_place_id=provider_place_id)
        return False
    return True


async def apply_result(
    db: AsyncSession, place: Place, result: GeocodeResult, *, call_id: int | None,
    overwrite_address: bool = True,
) -> Place:
    """Write a geocode onto a place, respecting who owns which column."""
    values = result.place_values()
    if not await _provider_place_free(db, place, result.provider_place_id):
        values.pop("provider_place_id", None)

    if place.is_zoho_linked or not overwrite_address:
        # Zoho owns the postal text on a Zoho-linked place; take only the
        # position and the provenance, never the address lines.
        values = {k: v for k, v in values.items() if k not in ZOHO_OWNED_PLACE_FIELDS}
        values.pop("formatted_address", None)

    for field_name, value in values.items():
        setattr(place, field_name, value)

    place.coordinates = WKTElement(f"POINT({result.longitude} {result.latitude})", srid=4326)
    place.geocoded_at = dt.datetime.now(dt.UTC)
    place.geocode_call_id = call_id
    # A provider returning a point is not evidence anyone can find the door.
    place.verification_status = VerificationStatus.GEOCODED_ONLY.value
    place.is_verified = False
    await db.flush()
    return place


async def geocode_place(
    db: AsyncSession, place: Place, *, provider: str | None = None,
) -> tuple[Place, GeocodeOutcome]:
    """Fill a place's coordinates from its postal fields."""
    text = address_text(place)
    if not text:
        raise GeoRuleError("This place has no address to geocode")
    settings = _settings()
    outcome = await geocode(db, GeoQuery(
        text=text,
        country=place.country_code or settings.GEOCODING_DEFAULT_COUNTRY or None,
        language=settings.GEOCODING_DEFAULT_LANGUAGE or None,
        limit=1,
    ), provider=provider)
    if outcome.best is None:
        return place, outcome
    return await apply_result(db, place, outcome.best, call_id=outcome.call_id), outcome


async def reverse_geocode_place(
    db: AsyncSession, place: Place, *, provider: str | None = None,
) -> tuple[Place, GeocodeOutcome]:
    """Fill a place's postal fields from its coordinates."""
    if place.latitude is None or place.longitude is None:
        raise GeoRuleError("This place has no coordinates to reverse-geocode")
    settings = _settings()
    outcome = await reverse_geocode(db, ReverseQuery(
        latitude=float(place.latitude), longitude=float(place.longitude),
        language=settings.GEOCODING_DEFAULT_LANGUAGE or None,
    ), provider=provider)
    if outcome.best is None:
        return place, outcome
    return await apply_result(db, place, outcome.best, call_id=outcome.call_id), outcome


# ── routing ─────────────────────────────────────────────────────────────────

async def route_matrix(
    db: AsyncSession,
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
    *, mode: str = "driving", provider: str | None = None,
) -> list[list[RouteLeg]]:
    """Distance and duration for every origin → destination pair.

    With no routing provider configured this returns great-circle distances
    and no durations, computed locally. That keeps ``distance_m`` populated
    everywhere while never inventing a travel time.
    """
    router = registry.router(provider)
    if getattr(router, "offline", False):
        return router.solve(origins, destinations, mode)         # type: ignore[attr-defined]

    router.check_configured()
    organization_id = await require_organization(db)
    request = router.build_matrix(origins, destinations, mode)
    digest = cache.request_hash(router.name, GeoApiType.DISTANCE_MATRIX, request.cache_params)

    hit = await cache.lookup(
        db, provider=router.name, api_type=GeoApiType.DISTANCE_MATRIX, digest=digest,
    )
    if hit is not None:
        return router.parse_matrix(hit.response_raw, mode)

    settings = _settings()
    try:
        call = await transport.execute(
            request, provider=router.name, rate_limit=settings.GEOCODING_MAX_CALLS_PER_MINUTE,
        )
    except (ProviderTransientError, ProviderRejected) as exc:
        await cache.record(
            db, organization_id=organization_id, provider=router.name,
            api_type=GeoApiType.DISTANCE_MATRIX, digest=digest,
            cache_params=request.cache_params, response_status=type(exc).__name__,
            servable=False, cost_units=router.cost_per_call,
        )
        logger.warning("geo.routing.failed", provider=router.name, error=str(exc),
                       fallback="haversine")
        # A distance is better than an error on a page that just wants a
        # number; the caller sees provider="haversine" and knows what it got.
        return registry.router("haversine").solve(origins, destinations, mode)   # type: ignore[attr-defined]

    matrix = router.parse_matrix(call.payload, mode)
    await cache.record(
        db, organization_id=organization_id, provider=router.name,
        api_type=GeoApiType.DISTANCE_MATRIX, digest=digest, cache_params=request.cache_params,
        payload=call.payload, response_status="OK", http_status=call.http_status,
        latency_ms=call.latency_ms, cost_units=router.cost_per_call,
        cache_days=_cache_days_routing(), empty=not any(matrix),
    )
    return matrix


def _cache_days_routing() -> int:
    # Roads change slowly; travel times change hourly. Cache the geometry
    # briefly and let live-traffic answers expire fast.
    return max(1, _settings().GEOCODING_ROUTING_CACHE_DAYS)


async def distance_between(
    db: AsyncSession, origin: tuple[float, float], destination: tuple[float, float],
    *, mode: str = "driving", provider: str | None = None,
) -> RouteLeg | None:
    matrix = await route_matrix(db, [origin], [destination], mode=mode, provider=provider)
    return matrix[0][0] if matrix and matrix[0] else None


__all__ = [
    "GeocodeOutcome",
    "address_text",
    "apply_result",
    "distance_between",
    "geocode",
    "geocode_place",
    "reverse_geocode",
    "reverse_geocode_place",
    "route_matrix",
]
