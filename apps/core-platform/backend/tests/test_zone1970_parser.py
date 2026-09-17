"""Unit tests for zone1970.tab parser and reference seeder data loading."""

from app.modules.users.seeders.reference import build_country_timezones, load_countries_data


def test_build_country_timezones_from_actual_file():
    zone_path = "data/timezones/zone1970.tab"
    mapping = build_country_timezones(zone_path)

    # India has Asia/Kolkata as primary
    assert "IN" in mapping
    assert mapping["IN"][0] == "Asia/Kolkata"

    # Multi-zone countries
    assert "US" in mapping
    assert len(mapping["US"]) > 1
    # New York is first in US zone list
    assert mapping["US"][0] == "America/New_York"

    assert "AU" in mapping
    assert len(mapping["AU"]) > 1


def test_load_countries_data_from_actual_file():
    json_path = "data/countries/countries.json"
    data = load_countries_data(json_path)
    assert len(data) >= 200

    # Verify India metadata
    india = next((c for c in data if c.get("cca2") == "IN"), None)
    assert india is not None
    assert india["name"]["common"] == "India"
    assert india["cca3"] == "IND"
