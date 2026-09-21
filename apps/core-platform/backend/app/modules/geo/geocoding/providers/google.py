"""Google Maps Geocoding API.

Docs: developers.google.com/maps/documentation/geocoding

Two things about Google that catch people out, both handled here:

* **A 200 is not a success.** Google answers ``200 OK`` with
  ``status: REQUEST_DENIED`` and an ``error_message`` when the key is wrong,
  unreferered or unbilled. Trusting the HTTP status turns a broken key into
  "no results found", silently, for as long as nobody checks.
* **Caching is contractual.** The licence permits storing geocoding results
  for 30 days, but ``place_id`` indefinitely. ``cache_days`` carries that into
  ``geo.geocode_api_calls.expires_at``, where one purge job enforces it.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.geo.distance import bounding_box
from app.modules.geo.enums import GeoApiType
from app.modules.geo.geocoding.base import GeocodingProvider
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeoQuery,
    ProviderRequest,
    ReverseQuery,
)

#: Google component type → our canonical key. Order matters for the few we
#: allow to fall back to a coarser type (see ``_components``).
_COMPONENT_MAP: dict[str, str] = {
    "premise": "building_name",
    "subpremise": "building_name",
    "sublocality_level_1": "sub_locality",
    "sublocality": "sub_locality",
    "neighborhood": "locality",
    "locality": "city",
    "postal_town": "city",
    "administrative_area_level_3": "taluka",
    "administrative_area_level_2": "district",
    "administrative_area_level_1": "state",
    "postal_code": "postal_code",
    "country": "country",
    "point_of_interest": "landmark",
}

#: Google's own precision statement, mapped onto our 0–1 confidence.
#: ROOFTOP means the building; APPROXIMATE can be the centre of a city.
_PRECISION: dict[str, float] = {
    "ROOFTOP": 1.0,
    "RANGE_INTERPOLATED": 0.8,
    "GEOMETRIC_CENTER": 0.6,
    "APPROXIMATE": 0.4,
}


class GoogleGeocoder(GeocodingProvider):
    name: ClassVar[str] = "google"
    label: ClassVar[str] = "Google Maps Geocoding"
    requires: ClassVar[tuple[str, ...]] = ("GOOGLE_MAPS_API_KEY",)
    cost_per_call: ClassVar[float] = 1.0
    cache_days: ClassVar[int | None] = 30          # licence ceiling

    BASE = "https://maps.googleapis.com/maps/api/geocode/json"

    # -- requests ---------------------------------------------------------
    def build_forward(self, query: GeoQuery) -> ProviderRequest:
        cache: dict[str, Any] = {"address": query.text}
        if query.country:
            cache["components"] = f"country:{query.country.upper()}"
        if query.language:
            cache["language"] = query.language
        if query.bias and query.bias_radius_m:
            min_lat, min_lng, max_lat, max_lng = bounding_box(query.bias, query.bias_radius_m)
            cache["bounds"] = f"{min_lat},{min_lng}|{max_lat},{max_lng}"
        return ProviderRequest(
            url=self.BASE,
            params={**cache, "key": self.settings.GOOGLE_MAPS_API_KEY},
            cache_params=cache,
        )

    def build_reverse(self, query: ReverseQuery) -> ProviderRequest:
        cache: dict[str, Any] = {"latlng": f"{query.latitude},{query.longitude}"}
        if query.language:
            cache["language"] = query.language
        return ProviderRequest(
            url=self.BASE,
            params={**cache, "key": self.settings.GOOGLE_MAPS_API_KEY},
            cache_params=cache,
        )

    # -- responses --------------------------------------------------------
    def check_payload(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return "MALFORMED"
        status = payload.get("status")
        # ZERO_RESULTS is a legitimate answer, not a fault: the address is not
        # findable, which is worth caching so we do not ask again tomorrow.
        return None if status in ("OK", "ZERO_RESULTS") else status

    def is_rejection(self, status: str | None) -> bool:
        # OVER_QUERY_LIMIT is per-second throttling → retryable.
        # The rest mean the request or the account is wrong → do not retry.
        return status in {"REQUEST_DENIED", "INVALID_REQUEST", "MALFORMED", "OVER_DAILY_LIMIT"}

    def parse(self, payload: Any, api_type: GeoApiType) -> list[GeocodeResult]:
        results = []
        for item in (payload or {}).get("results", []):
            location = (item.get("geometry") or {}).get("location") or {}
            if location.get("lat") is None or location.get("lng") is None:
                continue
            results.append(GeocodeResult(
                provider=self.name,
                latitude=float(location["lat"]),
                longitude=float(location["lng"]),
                formatted_address=item.get("formatted_address"),
                provider_place_id=item.get("place_id"),
                components=_components(item.get("address_components") or []),
                place_types=list(item.get("types") or []),
                confidence=_PRECISION.get((item.get("geometry") or {}).get("location_type"), 0.5),
                plus_code=(item.get("plus_code") or {}).get("global_code"),
                viewport=_viewport((item.get("geometry") or {}).get("viewport")),
                raw=item,
            ))
        return results


def _components(raw: list[dict]) -> dict[str, str | None]:
    """Flatten Google's typed component list into our postal columns.

    ``street_number`` and ``route`` arrive separately and are joined, because
    a street column holding "MG Road" without the number is not an address.
    """
    out: dict[str, str | None] = {}
    number = road = None
    for component in raw:
        long_name, short_name = component.get("long_name"), component.get("short_name")
        types = component.get("types") or []
        if "street_number" in types:
            number = long_name
        if "route" in types:
            road = long_name
        for type_name in types:
            key = _COMPONENT_MAP.get(type_name)
            if key and not out.get(key):
                out[key] = long_name
        if "administrative_area_level_1" in types and short_name:
            out["state_code"] = short_name
        if "country" in types and short_name:
            out["country_code"] = short_name.upper()
    if road:
        out["street"] = f"{number} {road}".strip() if number else road
    return out


def _viewport(viewport: dict | None) -> tuple[float, float, float, float] | None:
    if not viewport:
        return None
    northeast, southwest = viewport.get("northeast") or {}, viewport.get("southwest") or {}
    try:
        return (
            float(southwest["lng"]), float(southwest["lat"]),
            float(northeast["lng"]), float(northeast["lat"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
