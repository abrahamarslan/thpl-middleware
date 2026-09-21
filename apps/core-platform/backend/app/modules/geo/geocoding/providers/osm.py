"""The OpenStreetMap-derived geocoders: Nominatim and Pelias.

**Nominatim** is the reference OSM geocoder. The public instance at
openstreetmap.org is free and rate-limited to roughly one request per second,
requires a real ``User-Agent`` identifying the application, and forbids bulk
use. That makes it excellent for development and unacceptable for an import
run — hence ``max_calls_per_minute``, which the service enforces rather than
trusting anyone to remember. Self-host it and the limit is yours to raise.

**Pelias** is the other OSM geocoder, and the one that belongs next to
Valhalla: both came out of Mapzen, and Valhalla has no geocoder of its own.
If the goal is "no third-party dependency", the pair is Pelias for addresses
and Valhalla for routes, both self-hosted, both configured by base URL alone.

Self-hosted instances have no licence cache window, so ``cache_days`` is None
and the operator's ``GEOCODING_CACHE_DAYS`` applies.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.geo.enums import GeoApiType
from app.modules.geo.geocoding.base import GeocodingProvider
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeoQuery,
    ProviderRequest,
    ReverseQuery,
)

#: Nominatim ``address`` key → our canonical key. Several OSM keys collapse
#: onto one column: a place is a city whether OSM calls it city, town,
#: village or municipality, and asking every caller to check four keys is how
#: the city column ends up empty for villages.
_NOMINATIM_MAP: tuple[tuple[str, str], ...] = (
    ("building", "building_name"),
    ("house_name", "building_name"),
    ("road", "street"),
    ("pedestrian", "street"),
    ("neighbourhood", "sub_locality"),
    ("suburb", "sub_locality"),
    ("residential", "sub_locality"),
    ("quarter", "locality"),
    ("city_district", "locality"),
    ("city", "city"),
    ("town", "city"),
    ("village", "city"),
    ("municipality", "city"),
    ("county", "district"),
    ("state_district", "district"),
    ("subdistrict", "taluka"),
    ("state", "state"),
    ("postcode", "postal_code"),
    ("country", "country"),
    ("amenity", "landmark"),
)


class NominatimGeocoder(GeocodingProvider):
    name: ClassVar[str] = "nominatim"
    label: ClassVar[str] = "OpenStreetMap Nominatim"
    requires: ClassVar[tuple[str, ...]] = ("GEOCODING_NOMINATIM_USER_AGENT",)
    cost_per_call: ClassVar[float] = 0.0          # free; the cost is the policy
    cache_days: ClassVar[int | None] = None
    #: The public instance's published limit. Raise it only when self-hosting.
    max_calls_per_minute: ClassVar[int | None] = 60

    @property
    def _base(self) -> str:
        return (self.settings.GEOCODING_NOMINATIM_BASE_URL or
                "https://nominatim.openstreetmap.org").rstrip("/")

    def _headers(self) -> dict[str, str]:
        # Nominatim rejects requests without an identifying User-Agent, and
        # the policy asks for contact details in it.
        return {"User-Agent": self.settings.GEOCODING_NOMINATIM_USER_AGENT}

    def build_forward(self, query: GeoQuery) -> ProviderRequest:
        cache: dict[str, Any] = {
            "q": query.text, "format": "jsonv2", "addressdetails": 1, "limit": query.limit,
        }
        if query.country:
            cache["countrycodes"] = query.country.lower()
        if query.language:
            cache["accept-language"] = query.language
        return ProviderRequest(
            url=f"{self._base}/search", params=dict(cache),
            headers=self._headers(), cache_params=cache,
        )

    def build_reverse(self, query: ReverseQuery) -> ProviderRequest:
        cache: dict[str, Any] = {
            "lat": query.latitude, "lon": query.longitude,
            "format": "jsonv2", "addressdetails": 1,
        }
        if query.language:
            cache["accept-language"] = query.language
        return ProviderRequest(
            url=f"{self._base}/reverse", params=dict(cache),
            headers=self._headers(), cache_params=cache,
        )

    def check_payload(self, payload: Any) -> str | None:
        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            return f"ERROR:{message}"
        return None

    def parse(self, payload: Any, api_type: GeoApiType) -> list[GeocodeResult]:
        # /search returns a list, /reverse a single object.
        items = payload if isinstance(payload, list) else [payload] if payload else []
        results = []
        for item in items:
            if not isinstance(item, dict) or item.get("lat") is None:
                continue
            address = item.get("address") or {}
            components = _map_first(address, _NOMINATIM_MAP)
            if address.get("house_number") and components.get("street"):
                components["street"] = f"{address['house_number']} {components['street']}"
            if address.get("country_code"):
                components["country_code"] = str(address["country_code"]).upper()[:2]
            for key, value in address.items():
                if key.startswith("ISO3166-2-lvl") and isinstance(value, str):
                    components.setdefault("state_code", value.split("-")[-1])
            results.append(GeocodeResult(
                provider=self.name,
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
                formatted_address=item.get("display_name"),
                provider_place_id=str(item.get("osm_id") or item.get("place_id") or "") or None,
                components=components,
                place_types=[t for t in (item.get("category"), item.get("type")) if t],
                # `importance` ranks a result's prominence, not how well it
                # matches — a famous landmark scores high for a vague query.
                # Treated as a weak signal, never as precision.
                confidence=_importance(item.get("importance")),
                viewport=_nominatim_bbox(item.get("boundingbox")),
                raw=item,
            ))
        return results


class PeliasGeocoder(GeocodingProvider):
    name: ClassVar[str] = "pelias"
    label: ClassVar[str] = "Pelias (self-hosted / geocode.earth)"
    requires: ClassVar[tuple[str, ...]] = ("GEOCODING_PELIAS_BASE_URL",)
    cost_per_call: ClassVar[float] = 0.0
    cache_days: ClassVar[int | None] = None

    @property
    def _base(self) -> str:
        return self.settings.GEOCODING_PELIAS_BASE_URL.rstrip("/")

    def _auth(self) -> dict[str, Any]:
        key = getattr(self.settings, "GEOCODING_PELIAS_API_KEY", "")
        return {"api_key": key} if key else {}

    def build_forward(self, query: GeoQuery) -> ProviderRequest:
        cache: dict[str, Any] = {"text": query.text, "size": query.limit}
        if query.country:
            cache["boundary.country"] = query.country.upper()
        if query.bias:
            cache["focus.point.lat"] = query.bias[0]
            cache["focus.point.lon"] = query.bias[1]
        if query.language:
            cache["lang"] = query.language
        return ProviderRequest(
            url=f"{self._base}/v1/search", params={**cache, **self._auth()}, cache_params=cache,
        )

    def build_reverse(self, query: ReverseQuery) -> ProviderRequest:
        cache: dict[str, Any] = {
            "point.lat": query.latitude, "point.lon": query.longitude, "size": query.limit,
        }
        if query.language:
            cache["lang"] = query.language
        return ProviderRequest(
            url=f"{self._base}/v1/reverse", params={**cache, **self._auth()}, cache_params=cache,
        )

    def parse(self, payload: Any, api_type: GeoApiType) -> list[GeocodeResult]:
        results = []
        for feature in (payload or {}).get("features", []):
            coordinates = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coordinates) < 2:
                continue
            properties = feature.get("properties") or {}
            street = properties.get("street")
            if properties.get("housenumber") and street:
                street = f"{properties['housenumber']} {street}"
            components = {
                "building_name": properties.get("name") if not street else None,
                "street": street,
                "sub_locality": properties.get("neighbourhood") or properties.get("borough"),
                "locality": properties.get("locality"),
                "city": properties.get("localadmin") or properties.get("locality"),
                "district": properties.get("county"),
                "taluka": properties.get("localadmin"),
                "state": properties.get("region"),
                "state_code": (properties.get("region_a") or "").split("-")[-1] or None,
                "postal_code": properties.get("postalcode"),
                "country": properties.get("country"),
                "country_code": _alpha2(properties.get("country_a")),
            }
            results.append(GeocodeResult(
                provider=self.name,
                latitude=float(coordinates[1]),
                longitude=float(coordinates[0]),
                formatted_address=properties.get("label"),
                provider_place_id=properties.get("gid") or properties.get("id"),
                components={k: v for k, v in components.items() if v},
                place_types=[properties["layer"]] if properties.get("layer") else [],
                confidence=_float(properties.get("confidence")),
                viewport=_pelias_bbox(feature.get("bbox")),
                raw=feature,
            ))
        return results


# ── helpers ─────────────────────────────────────────────────────────────────

def _map_first(source: dict, mapping: tuple[tuple[str, str], ...]) -> dict[str, str | None]:
    """Apply an ordered (source key → our key) mapping, first match wins."""
    out: dict[str, str | None] = {}
    for source_key, canonical in mapping:
        value = source.get(source_key)
        if value and not out.get(canonical):
            out[canonical] = str(value)
    return out


def _importance(value: Any) -> float | None:
    number = _float(value)
    return None if number is None else max(0.0, min(1.0, number))


def _float(value: Any) -> float | None:
    try:
        return float(value)                                   # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _alpha2(country_a: Any) -> str | None:
    """Pelias reports ISO alpha-3 ("IND"); our column holds alpha-2."""
    if not isinstance(country_a, str) or not country_a:
        return None
    return {"IND": "IN", "USA": "US", "GBR": "GB", "ARE": "AE"}.get(country_a.upper(), country_a[:2].upper())


def _nominatim_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    """Nominatim gives [min_lat, max_lat, min_lng, max_lng] as strings."""
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        return None
    try:
        min_lat, max_lat, min_lng, max_lng = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None
    return (min_lng, min_lat, max_lng, max_lat)


def _pelias_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return tuple(float(v) for v in bbox)               # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None
