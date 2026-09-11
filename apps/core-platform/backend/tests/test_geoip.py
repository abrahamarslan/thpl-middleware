"""GeoIP lookups against the real MaxMind databases (skips if absent).

The .mmdb files are licensed and git-ignored, so these tests skip cleanly on a
bare checkout and run for real wherever the files are present.
"""

from pathlib import Path

import pytest

from app.common import geoip
from app.core.conf import settings

_GEOIP_DIR = Path(__file__).resolve().parents[2] / "deployment" / "config" / "geoip"
_CITY_DB = _GEOIP_DIR / "GeoLite2-City.mmdb"
_COUNTRY_DB = _GEOIP_DIR / "GeoLite2-Country.mmdb"
_ASN_DB = _GEOIP_DIR / "GeoLite2-ASN.mmdb"

pytestmark = pytest.mark.skipif(not _CITY_DB.exists(), reason="GeoLite2 databases not present")


def _enable(monkeypatch, *, city: Path | None, country: Path | None = None) -> None:
    monkeypatch.setattr(settings, "GEOIP_ENABLED", True)
    monkeypatch.setattr(settings, "GEOIP_CITY_DB_PATH", str(city) if city else "")
    monkeypatch.setattr(settings, "GEOIP_COUNTRY_DB_PATH", str(country) if country else "")
    geoip._reader.cache_clear()


def test_city_lookup_for_public_ip(monkeypatch):
    _enable(monkeypatch, city=_CITY_DB)
    try:
        location = geoip.lookup_ip("8.8.8.8")
        assert location is not None
        assert location.ip == "8.8.8.8"
        assert location.country_code == "US"
        assert location.country  # e.g. "United States"
        assert location.display  # non-empty human string
    finally:
        geoip._reader.cache_clear()


def test_country_only_db_lookup(monkeypatch):
    if not _COUNTRY_DB.exists():
        pytest.skip("GeoLite2-Country.mmdb not present")
    _enable(monkeypatch, city=None, country=_COUNTRY_DB)
    try:
        location = geoip.lookup_ip("1.1.1.1")
        assert location is not None
        assert location.country_code  # country-only DB still resolves the country
    finally:
        geoip._reader.cache_clear()


def test_private_and_reserved_ips_are_skipped(monkeypatch):
    _enable(monkeypatch, city=_CITY_DB)
    try:
        assert geoip.lookup_ip("10.0.0.1") is None
        assert geoip.lookup_ip("127.0.0.1") is None
        assert geoip.lookup_ip(None) is None
    finally:
        geoip._reader.cache_clear()


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "GEOIP_ENABLED", False)
    geoip._reader.cache_clear()
    try:
        assert geoip.lookup_ip("8.8.8.8") is None
    finally:
        geoip._reader.cache_clear()


def test_asn_database_is_not_a_location_source(monkeypatch):
    if not _ASN_DB.exists():
        pytest.skip("GeoLite2-ASN.mmdb not present")
    _enable(monkeypatch, city=_ASN_DB)
    try:
        assert geoip.lookup_ip("8.8.8.8") is None  # ASN is not city/country
    finally:
        geoip._reader.cache_clear()
