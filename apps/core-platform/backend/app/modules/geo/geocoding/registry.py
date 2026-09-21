"""Provider registry and the configured chain.

Configuration is three settings:

    GEOCODING_PROVIDER            the primary, e.g. "google"
    GEOCODING_FALLBACK_PROVIDERS  comma-separated, tried in order
    ROUTING_PROVIDER              "" = the offline straight-line floor

A fallback chain is not redundancy theatre. Geocoding upstreams fail in ways
that are invisible from here — a key hits its daily cap at 4pm, a self-hosted
Pelias is mid-redeploy, Google returns ZERO_RESULTS for an address Nominatim
knows because its OSM coverage of that district is better. Falling through
costs one extra call on the unhappy path and turns an outage into a slower
answer.

Unconfigured providers are dropped from the chain rather than raising, so an
operator can name a chain once and enable keys over time.
"""

from __future__ import annotations

import structlog

from app.core.conf import settings as default_settings
from app.modules.geo.geocoding.base import GeocodingProvider, RoutingProvider
from app.modules.geo.geocoding.providers import GEOCODERS, ROUTERS, HaversineRouting
from app.modules.geo.geocoding.types import ProviderNotConfigured

logger = structlog.get_logger("app.geo.geocoding")

_GEOCODERS: dict[str, type[GeocodingProvider]] = {cls.name: cls for cls in GEOCODERS}
_ROUTERS: dict[str, type[RoutingProvider]] = {cls.name: cls for cls in ROUTERS}


def register_geocoder(cls: type[GeocodingProvider]) -> type[GeocodingProvider]:
    _GEOCODERS[cls.name] = cls
    return cls


def register_router(cls: type[RoutingProvider]) -> type[RoutingProvider]:
    _ROUTERS[cls.name] = cls
    return cls


def geocoder_names() -> list[str]:
    return sorted(_GEOCODERS)


def router_names() -> list[str]:
    return sorted(_ROUTERS)


def geocoder(name: str, settings=None) -> GeocodingProvider:
    """One provider by name. Raises if the name is unknown."""
    cls = _GEOCODERS.get((name or "").strip().lower())
    if cls is None:
        raise ProviderNotConfigured(
            f"unknown geocoding provider '{name}'; available: {', '.join(geocoder_names())}"
        )
    return cls(settings or default_settings)


def router(name: str | None = None, settings=None) -> RoutingProvider:
    """The routing provider, defaulting to the offline straight-line floor."""
    settings = settings or default_settings
    chosen = (name if name is not None else settings.ROUTING_PROVIDER or "").strip().lower()
    if not chosen:
        return HaversineRouting(settings)
    cls = _ROUTERS.get(chosen)
    if cls is None:
        raise ProviderNotConfigured(
            f"unknown routing provider '{chosen}'; available: {', '.join(router_names())}"
        )
    return cls(settings)


def _chain_names(settings) -> list[str]:
    names = [(settings.GEOCODING_PROVIDER or "").strip().lower()]
    names += [
        part.strip().lower()
        for part in (settings.GEOCODING_FALLBACK_PROVIDERS or "").split(",")
    ]
    seen, ordered = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def geocoder_chain(settings=None) -> list[GeocodingProvider]:
    """Configured providers, primary first, unusable ones dropped."""
    settings = settings or default_settings
    if not settings.GEOCODING_ENABLED:
        return []
    chain: list[GeocodingProvider] = []
    for name in _chain_names(settings):
        cls = _GEOCODERS.get(name)
        if cls is None:
            logger.warning("geo.geocoding.unknown_provider", provider=name)
            continue
        provider = cls(settings)
        missing = provider.missing_settings()
        if missing:
            logger.warning("geo.geocoding.provider_unconfigured", provider=name, missing=missing)
            continue
        chain.append(provider)
    return chain


def describe(settings=None) -> list[dict]:
    """Every known provider and whether it could run right now — the body of
    ``GET /api/geocoding/providers``. Reports which settings are missing, and
    never their values."""
    settings = settings or default_settings
    chain = [provider.name for provider in geocoder_chain(settings)]
    active_router = router(settings=settings)

    rows = []
    for name, cls in sorted(_GEOCODERS.items()):
        provider = cls(settings)
        missing = provider.missing_settings()
        rows.append({
            "name": name,
            "label": cls.label or name,
            "kind": "geocoding",
            "configured": not missing,
            "missing_settings": missing,
            "in_chain": name in chain,
            "chain_position": chain.index(name) + 1 if name in chain else None,
            "cost_per_call": cls.cost_per_call,
            "cache_days": cls.cache_days if cls.cache_days is not None else settings.GEOCODING_CACHE_DAYS,
            "max_calls_per_minute": cls.max_calls_per_minute or settings.GEOCODING_MAX_CALLS_PER_MINUTE,
        })
    for name, cls in sorted(_ROUTERS.items()):
        provider = cls(settings)
        missing = provider.missing_settings()
        rows.append({
            "name": name,
            "label": cls.label or name,
            "kind": "routing",
            "configured": not missing,
            "missing_settings": missing,
            "in_chain": name == active_router.name,
            "chain_position": 1 if name == active_router.name else None,
            "cost_per_call": cls.cost_per_call,
            "cache_days": None,
            "max_calls_per_minute": settings.GEOCODING_MAX_CALLS_PER_MINUTE,
        })
    return rows


__all__ = [
    "describe",
    "geocoder",
    "geocoder_chain",
    "geocoder_names",
    "register_geocoder",
    "register_router",
    "router",
    "router_names",
]
