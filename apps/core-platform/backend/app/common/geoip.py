"""GeoIP lookups (MaxMind GeoLite2) with graceful degradation.

Request-audit context for auth events (login, signup, password reset) needs an
IP → place mapping. The database is **not bundled** (MaxMind licensing), so this
module always degrades to ``None`` when disabled, unconfigured, or unreadable —
GeoIP is enrichment, never a hard dependency of the request path.

The reader is a lazy, process-wide singleton (memory-mapped) so a lookup is a
microsecond-scale in-process call. Tests patch ``lookup_ip`` or leave
``GEOIP_ENABLED`` false.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog

from app.core.conf import settings

logger = structlog.get_logger("app.geoip")


@dataclass(frozen=True, slots=True)
class GeoLocation:
    ip: str
    city: str | None = None
    region: str | None = None
    country: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None

    @property
    def display(self) -> str:
        """Human-readable 'City, Region, Country' (de-duplicated)."""
        parts: list[str] = []
        for value in (self.city, self.region, self.country):
            if value and value not in parts:
                parts.append(value)
        return ", ".join(parts) if parts else "Unknown location"


def is_public_ip(ip: str | None) -> bool:
    """True only for globally-routable addresses worth a GeoIP lookup."""
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


@lru_cache
def _reader() -> Any | None:
    """Lazy reader singleton (City preferred, Country fallback). None if off."""
    if not settings.GEOIP_ENABLED:
        return None
    path = settings.GEOIP_CITY_DB_PATH or settings.GEOIP_COUNTRY_DB_PATH
    if not path:
        logger.warning("geoip_enabled_but_no_db_configured")
        return None
    try:
        import geoip2.database

        reader = geoip2.database.Reader(path, mode=geoip2.database.MODE_MMAP_EXT)
        logger.info("geoip_reader_loaded", path=path, database_type=reader.metadata().database_type)
        return reader
    except Exception as e:  # noqa: BLE001 — enrichment must never break a request
        logger.error("geoip_reader_load_failed", path=path, error=str(e))
        return None


def _country_fields(response: Any) -> tuple[str | None, str | None]:
    """(name, iso_code), falling back to registered_country.

    Some ranges (e.g. Cloudflare 1.1.1.1) have an empty ``country`` but a
    populated ``registered_country`` — without the fallback the lookup would
    report no country at all.
    """
    country = response.country
    if not country.iso_code:
        country = response.registered_country
    return country.name, country.iso_code


def _city_response(response: Any, ip: str) -> GeoLocation:
    country_name, country_code = _country_fields(response)
    return GeoLocation(
        ip=ip,
        city=response.city.name,
        region=response.subdivisions.most_specific.name,
        country=country_name,
        country_code=country_code,
        latitude=response.location.latitude,
        longitude=response.location.longitude,
        timezone=response.location.time_zone,
    )


def lookup_ip(ip: str | None) -> GeoLocation | None:
    """Resolve a public IP to a location, or None when unavailable."""
    if not settings.GEOIP_ENABLED or not is_public_ip(ip):
        return None
    reader = _reader()
    if reader is None:
        return None
    try:
        import geoip2.errors

        database_type = (reader.metadata().database_type or "").lower()
        if "city" in database_type:
            return _city_response(reader.city(ip), ip)
        if "country" in database_type:
            response = reader.country(ip)
            country_name, country_code = _country_fields(response)
            return GeoLocation(ip=ip, country=country_name, country_code=country_code)
        return None
    except geoip2.errors.AddressNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("geoip_lookup_failed", ip=ip, error=str(e))
        return None
