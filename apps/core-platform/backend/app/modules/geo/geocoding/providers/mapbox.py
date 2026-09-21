"""Mapbox Geocoding.

Docs: docs.mapbox.com/api/search/geocoding

Mapbox is mid-migration: v6 (``/search/geocode/v6``) is what new accounts get,
v5 (``/geocoding/v5/mapbox.places``) is what existing integrations still run.
The two return the same information in different shapes — v5 puts ancestry in
a ``context`` **array** keyed by id prefix, v6 in a ``context`` **object**
keyed by layer. ``GEOCODING_MAPBOX_BASE_URL`` selects the endpoint and the
parser accepts either shape, so switching versions is a URL change rather
than a code change.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from app.modules.geo.enums import GeoApiType
from app.modules.geo.geocoding.base import GeocodingProvider
from app.modules.geo.geocoding.types import (
    GeocodeResult,
    GeoQuery,
    ProviderRequest,
    ReverseQuery,
)

#: v5 ``context`` id prefix / v6 ``context`` key → our canonical key.
_CONTEXT_MAP: dict[str, str] = {
    "address": "street",
    "street": "street",
    "neighborhood": "sub_locality",
    "neighbourhood": "sub_locality",
    "locality": "locality",
    "place": "city",
    "district": "district",
    "region": "state",
    "postcode": "postal_code",
    "country": "country",
}


class MapboxGeocoder(GeocodingProvider):
    name: ClassVar[str] = "mapbox"
    label: ClassVar[str] = "Mapbox Geocoding"
    requires: ClassVar[tuple[str, ...]] = ("MAPBOX_ACCESS_TOKEN",)
    cost_per_call: ClassVar[float] = 1.0
    cache_days: ClassVar[int | None] = 30

    @property
    def _base(self) -> str:
        return (self.settings.GEOCODING_MAPBOX_BASE_URL or
                "https://api.mapbox.com/search/geocode/v6").rstrip("/")

    @property
    def _is_v6(self) -> bool:
        return "/v6" in self._base

    @property
    def cache_variant(self) -> str:
        # v5 and v6 answer the same question with different payloads; a cache
        # entry written by one must never be parsed as the other.
        return "v6" if self._is_v6 else "v5"

    def build_forward(self, query: GeoQuery) -> ProviderRequest:
        cache: dict[str, Any] = {"limit": query.limit}
        if query.country:
            cache["country"] = query.country.lower()
        if query.language:
            cache["language"] = query.language
        if query.bias:
            cache["proximity"] = f"{query.bias[1]},{query.bias[0]}"      # lng,lat

        if self._is_v6:
            cache["q"] = query.text
            url = f"{self._base}/forward"
        else:
            # v5 puts the query in the path; it must be escaped.
            url = f"{self._base}/{quote(query.text, safe='')}.json"
            cache["query"] = query.text
        return ProviderRequest(
            url=url,
            params={**{k: v for k, v in cache.items() if k != "query"},
                    "access_token": self.settings.MAPBOX_ACCESS_TOKEN},
            cache_params=cache,
        )

    def build_reverse(self, query: ReverseQuery) -> ProviderRequest:
        cache: dict[str, Any] = {"limit": query.limit}
        if query.language:
            cache["language"] = query.language
        if self._is_v6:
            cache["longitude"] = query.longitude
            cache["latitude"] = query.latitude
            url = f"{self._base}/reverse"
            params = {**cache, "access_token": self.settings.MAPBOX_ACCESS_TOKEN}
        else:
            url = f"{self._base}/{query.longitude},{query.latitude}.json"
            cache["point"] = f"{query.longitude},{query.latitude}"
            params = {"limit": query.limit, "access_token": self.settings.MAPBOX_ACCESS_TOKEN}
        return ProviderRequest(url=url, params=params, cache_params=cache)

    def check_payload(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return "MALFORMED"
        if payload.get("message") and "features" not in payload:
            return "REQUEST_DENIED"
        return None

    def parse(self, payload: Any, api_type: GeoApiType) -> list[GeocodeResult]:
        results = []
        for feature in (payload or {}).get("features", []):
            properties = feature.get("properties") or {}
            point = _coordinates(feature, properties)
            if point is None:
                continue
            longitude, latitude = point
            components = _context(properties.get("context") or feature.get("context") or [])
            street = _street(feature, properties, components.get("street"))
            if street:
                components["street"] = street
            results.append(GeocodeResult(
                provider=self.name,
                latitude=latitude,
                longitude=longitude,
                formatted_address=(properties.get("full_address") or properties.get("place_formatted")
                                   or feature.get("place_name")),
                provider_place_id=(properties.get("mapbox_id") or feature.get("id")),
                components=components,
                place_types=_place_types(feature, properties),
                confidence=_confidence(feature, properties),
                viewport=_bbox(feature.get("bbox") or properties.get("bbox")),
                raw=feature,
            ))
        return results


def _coordinates(feature: dict, properties: dict) -> tuple[float, float] | None:
    """(longitude, latitude), from whichever shape the account returns."""
    coordinates = properties.get("coordinates")
    if isinstance(coordinates, dict):                                    # v6
        try:
            return float(coordinates["longitude"]), float(coordinates["latitude"])
        except (KeyError, TypeError, ValueError):
            return None
    raw = feature.get("center") or (feature.get("geometry") or {}).get("coordinates")   # v5
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            return None
    return None


def _street(feature: dict, properties: dict, context_street: str | None) -> str | None:
    """The street line WITH its house number, from either API version.

    Both versions keep the number apart from the street name, in different
    places. A street column holding "Mahatma Gandhi Road" without the 12 is
    not an address, so the two are rejoined here rather than left to callers.
    """
    context = properties.get("context")
    if isinstance(context, dict):                                        # v6
        address = context.get("address")
        if isinstance(address, dict):
            number = address.get("address_number")
            name = address.get("street_name") or context_street
            if number and name:
                return f"{number} {name}"
            if address.get("name"):
                return str(address["name"])
        # An address feature's own `name` is already the full line.
        if properties.get("feature_type") == "address" and properties.get("name"):
            return str(properties["name"])

    if "address" in (feature.get("place_type") or []) and feature.get("text"):   # v5
        number = feature.get("address")
        return f"{number} {feature['text']}" if number else str(feature["text"])

    return context_street


def _context(context: Any) -> dict[str, str | None]:
    out: dict[str, str | None] = {}

    def take(key: str, entry: dict) -> None:
        canonical = _CONTEXT_MAP.get(key)
        name = entry.get("name") or entry.get("text")
        if canonical and name and not out.get(canonical):
            out[canonical] = name
        if key == "region":
            code = entry.get("region_code") or entry.get("short_code") or ""
            if code:
                out["state_code"] = code.split("-")[-1].upper()
        if key == "country":
            code = entry.get("country_code") or entry.get("short_code") or ""
            if code:
                out["country_code"] = code.upper()[:2]

    if isinstance(context, dict):                                        # v6
        for key, entry in context.items():
            if isinstance(entry, dict):
                take(key, entry)
    elif isinstance(context, list):                                      # v5
        for entry in context:
            if isinstance(entry, dict) and entry.get("id"):
                take(str(entry["id"]).split(".")[0], entry)
    return out


def _place_types(feature: dict, properties: dict) -> list[str]:
    if properties.get("feature_type"):
        return [properties["feature_type"]]
    return list(feature.get("place_type") or [])


def _confidence(feature: dict, properties: dict) -> float | None:
    """v6 grades the match, v5 scores relevance 0–1."""
    match_code = properties.get("match_code") or {}
    grade = match_code.get("confidence")
    if grade:
        return {"exact": 1.0, "high": 0.85, "medium": 0.6, "low": 0.3}.get(grade, 0.5)
    relevance = feature.get("relevance")
    return float(relevance) if isinstance(relevance, (int, float)) else None


def _bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return tuple(float(value) for value in bbox)                 # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None
