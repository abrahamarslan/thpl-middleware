"""Bundled providers.

Adding one is: subclass ``GeocodingProvider`` or ``RoutingProvider``, build a
request, parse a payload, list it below. Nothing else in the platform changes
— resilience, caching, provenance and cost accounting are the service's job,
not the provider's.

Out-of-tree providers register at startup with
``registry.register_geocoder(cls)`` / ``register_router(cls)``.
"""

from app.modules.geo.geocoding.providers.google import GoogleGeocoder
from app.modules.geo.geocoding.providers.mapbox import MapboxGeocoder
from app.modules.geo.geocoding.providers.osm import NominatimGeocoder, PeliasGeocoder
from app.modules.geo.geocoding.providers.routing import (
    GoogleRouting,
    HaversineRouting,
    MapboxRouting,
    ValhallaRouting,
)

GEOCODERS = (GoogleGeocoder, MapboxGeocoder, NominatimGeocoder, PeliasGeocoder)
ROUTERS = (ValhallaRouting, GoogleRouting, MapboxRouting, HaversineRouting)

__all__ = [
    "GEOCODERS",
    "ROUTERS",
    "GoogleGeocoder",
    "GoogleRouting",
    "HaversineRouting",
    "MapboxGeocoder",
    "MapboxRouting",
    "NominatimGeocoder",
    "PeliasGeocoder",
    "ValhallaRouting",
]
