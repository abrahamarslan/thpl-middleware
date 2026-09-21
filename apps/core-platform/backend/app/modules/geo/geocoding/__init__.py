"""Geocoding, reverse geocoding and routing behind a swappable provider layer.

    types.py      the vocabulary every provider is translated into
    base.py       the contract: build a request, parse a payload — no HTTP
    providers/    Google · Mapbox · Nominatim · Pelias · Valhalla · haversine
    registry.py   name → class, and the configured fallback chain
    transport.py  timeouts, retries, rate limit, circuit breaker
    cache.py      geo.geocode_api_calls — cache, audit trail and spend ledger
    service.py    the orchestration, written once for every provider
    api.py        /api/geocoding

See docs/geo/geocoding.md.
"""

from app.modules.geo.geocoding.service import (
    GeocodeOutcome,
    distance_between,
    geocode,
    geocode_place,
    reverse_geocode,
    reverse_geocode_place,
    route_matrix,
)
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeocodingError,
    GeocodingUnavailable,
    GeoQuery,
    ProviderNotConfigured,
    ReverseQuery,
    RouteLeg,
)

__all__ = [
    "GeoQuery",
    "GeocodeOutcome",
    "GeocodeResult",
    "GeocodingError",
    "GeocodingUnavailable",
    "ProviderNotConfigured",
    "ReverseQuery",
    "RouteLeg",
    "distance_between",
    "geocode",
    "geocode_place",
    "reverse_geocode",
    "reverse_geocode_place",
    "route_matrix",
]
