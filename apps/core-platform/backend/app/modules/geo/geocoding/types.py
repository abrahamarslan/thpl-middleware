"""The vocabulary every geocoding provider is translated into.

A provider's own taxonomy never escapes its module. Google says
``administrative_area_level_2``, Mapbox says ``context[].id = district.NNN``,
Nominatim says ``state_district`` — and all three mean the column this
platform calls ``district``. The translation happens once, in the provider,
into ``AddressComponents``; everything downstream sees one shape.

That is the whole reason this layer exists. Without it, swapping providers is
a migration of every caller instead of one line of configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

#: Canonical postal keys — exactly the writable columns of ``geo.places``, so
#: a result can be applied to a place without a second mapping step.
ADDRESS_COMPONENTS: tuple[str, ...] = (
    "building_name", "street", "street2", "landmark", "sub_locality", "locality",
    "city", "district", "taluka", "state", "state_code", "postal_code",
    "country", "country_code",
)

AddressComponents = dict[str, str | None]

GeoMode = Literal["forward", "reverse"]


@dataclass(frozen=True, slots=True)
class GeoQuery:
    """A forward geocode: free text plus whatever narrows it.

    ``bias`` and ``country`` matter more than they look. "MG Road" exists in
    forty Indian cities; without a bias the first answer is a coin toss, and
    the coin does not land on the customer's city.
    """

    text: str
    country: str | None = None                  # ISO 3166-1 alpha-2, e.g. "IN"
    bias: tuple[float, float] | None = None     # (latitude, longitude) to prefer
    bias_radius_m: float | None = None
    language: str | None = None
    limit: int = 5

    def normalized(self) -> dict[str, Any]:
        """The cache identity of this query — never the credentials."""
        return {
            "text": " ".join(self.text.lower().split()),
            "country": (self.country or "").upper() or None,
            "bias": [round(c, 4) for c in self.bias] if self.bias else None,
            "language": self.language,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class ReverseQuery:
    """A reverse geocode: a point, and how precisely to answer it."""

    latitude: float
    longitude: float
    language: str | None = None
    limit: int = 1

    def normalized(self) -> dict[str, Any]:
        # ~11 m of precision. Rounding IS the cache policy: two fixes from the
        # same doorway must hit one cached answer, or the cache never warms.
        return {
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "language": self.language,
            "limit": self.limit,
        }


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    """One normalized answer. ``raw`` is kept only long enough to be stored in
    ``geo.geocode_api_calls``; nothing downstream reads it."""

    provider: str
    latitude: float
    longitude: float
    formatted_address: str | None = None
    provider_place_id: str | None = None
    components: AddressComponents = field(default_factory=dict)
    place_types: list[str] = field(default_factory=list)
    confidence: float | None = None             # normalized to 0–1
    plus_code: str | None = None
    timezone: str | None = None
    #: (min_lng, min_lat, max_lng, max_lat) — provider viewport, if any.
    viewport: tuple[float, float, float, float] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def place_values(self) -> dict[str, Any]:
        """The subset that can be written straight onto ``geo.places``."""
        values: dict[str, Any] = {k: v for k, v in self.components.items() if v}
        values["formatted_address"] = self.formatted_address
        values["provider"] = self.provider
        values["provider_place_id"] = self.provider_place_id
        values["geocode_confidence"] = self.confidence
        values["plus_code"] = self.plus_code
        values["place_types"] = self.place_types or None
        values["address_components"] = dict(self.components)
        if self.timezone:
            values["timezone"] = self.timezone
        return {k: v for k, v in values.items() if v is not None}


@dataclass(frozen=True, slots=True)
class RouteLeg:
    """One origin → destination pair, measured by a routing provider."""

    distance_m: float
    duration_s: float | None = None
    provider: str = ""
    mode: str = "driving"
    geometry: str | None = None                 # encoded polyline, if returned
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """What a provider wants called — built by the provider, executed by the
    service. See ``base.py`` for why the two are separate.

    ``cache_params`` is what identifies the request for caching and is also
    what gets stored. It must never contain an API key: the raw-payload table
    is readable by anyone who can read the tenant's data, and a credential
    that lands in it is a credential that has leaked.
    """

    url: str
    params: dict[str, Any] = field(default_factory=dict)
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    cache_params: dict[str, Any] = field(default_factory=dict)


# ── errors ──────────────────────────────────────────────────────────────────

class GeocodingError(Exception):
    """Base for everything this package raises."""


class ProviderNotConfigured(GeocodingError):
    """Missing key, missing base URL, or the provider is switched off."""


class ProviderTransientError(GeocodingError):
    """Timeout, connection failure, 5xx, or the provider's own rate limit.
    Retryable, and the reason to try the next provider in the chain."""


class ProviderRejected(GeocodingError):
    """The provider answered, and the answer is no: bad key, quota exhausted,
    malformed request. Retrying is pointless; the chain moves on but the
    outcome is recorded so the misconfiguration surfaces."""


class GeocodingUnavailable(GeocodingError):
    """Every configured provider failed, or none is configured."""


__all__ = [
    "ADDRESS_COMPONENTS",
    "AddressComponents",
    "GeoMode",
    "GeoQuery",
    "GeocodeResult",
    "GeocodingError",
    "GeocodingUnavailable",
    "ProviderNotConfigured",
    "ProviderRejected",
    "ProviderRequest",
    "ProviderTransientError",
    "ReverseQuery",
    "RouteLeg",
]
