"""Field-mapping engine — extraction, transforms, inbound/outbound builds."""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.modules.zoho.sync.config import FieldMapping as F
from app.modules.zoho.sync.config import resolve_module_config
from app.modules.zoho.sync.mapper import (
    MISSING,
    extract,
    flatten_custom_fields,
    map_inbound,
    map_outbound,
    parse_zoho_datetime,
)


def _cfg(field_map):
    return resolve_module_config(module="t", endpoint="/t", zoho_id_attr="t_id", field_map=field_map)


# ── extract ──────────────────────────────────────────────────────────────────

def test_extract_dotted_paths():
    payload = {"address": {"city": "Chennai", "geo": {"lat": 13.08}}}
    assert extract(payload, "address.city") == "Chennai"
    assert extract(payload, "address.geo.lat") == 13.08
    assert extract(payload, "address.zip") is MISSING
    assert extract(payload, "missing.deep.path") is MISSING


# ── transforms ───────────────────────────────────────────────────────────────

def test_parse_zoho_datetime_formats():
    dt = parse_zoho_datetime("2016-06-11T17:38:06-0700")
    assert dt is not None and dt.utcoffset().total_seconds() == -7 * 3600

    plain_date = parse_zoho_datetime("2016-02-18")
    assert plain_date == datetime(2016, 2, 18, tzinfo=UTC)

    assert parse_zoho_datetime(" ") is None
    assert parse_zoho_datetime(None) is None
    assert parse_zoho_datetime("not-a-date") is None


def test_map_inbound_applies_transforms():
    cfg = _cfg([
        F(zoho="name", local="name", transform="str"),
        F(zoho="fiscal_year_start_month", local="fiscal_month", transform="int"),
        F(zoho="tax_group_enabled", local="tax_on", transform="bool"),
        F(zoho="rate", local="rate", transform="decimal"),
        F(zoho="account_created_date", local="created", transform="zoho_date"),
    ])
    values = map_inbound(cfg, {
        "name": "  Zillum Inc  ",
        "fiscal_year_start_month": "3",
        "tax_group_enabled": "true",
        "rate": "18.5",
        "account_created_date": "2012-02-15",
    })
    assert values == {
        "name": "Zillum Inc",
        "fiscal_month": 3,
        "tax_on": True,
        "rate": Decimal("18.5"),
        "created": date(2012, 2, 15),
    }


def test_map_inbound_skips_missing_keys_never_nulls():
    """A partial payload must not overwrite existing data with NULLs."""
    cfg = _cfg([F(zoho="name", local="name"), F(zoho="email", local="email")])
    values = map_inbound(cfg, {"name": "Acme"})
    assert values == {"name": "Acme"}  # email absent — column untouched


def test_map_inbound_bad_value_falls_back_to_default():
    cfg = _cfg([F(zoho="count", local="count", transform="int", default=0)])
    assert map_inbound(cfg, {"count": "not-a-number"}) == {"count": 0}


def test_map_inbound_zoho_blank_strings_normalised():
    # Zoho loves sending " " for empty attributes (see organizations.md example)
    cfg = _cfg([F(zoho="user_status", local="user_status", transform="str")])
    assert map_inbound(cfg, {"user_status": " "}) == {"user_status": None}


# ── outbound ─────────────────────────────────────────────────────────────────

class _Row:
    name = "Zillum Inc"
    email = None
    address_city = "Chennai"
    internal_only = "secret"
    created = date(2012, 2, 15)


def test_map_outbound_rebuilds_nested_paths_and_skips_none():
    cfg = _cfg([
        F(zoho="name", local="name"),
        F(zoho="email", local="email"),
        F(zoho="address.city", local="address_city"),
        F(zoho="user_role", local="internal_only", outbound=False),
        F(zoho="account_created_date", local="created"),
    ])
    payload = map_outbound(cfg, _Row())
    assert payload == {
        "name": "Zillum Inc",
        "address": {"city": "Chennai"},
        "account_created_date": "2012-02-15",
    }
    assert "email" not in payload           # None dropped
    assert "user_role" not in payload       # outbound=False respected


# ── custom fields ────────────────────────────────────────────────────────────

def test_flatten_custom_fields_to_hstore_shape():
    payload = {"custom_fields": [
        {"customfield_id": "1", "api_name": "cf_region", "value": "South"},
        {"label": "Priority", "value": 3},
        {"api_name": "cf_empty", "value": None},
        "garbage-entry",
    ]}
    assert flatten_custom_fields(payload) == {
        "cf_region": "South",
        "Priority": "3",
        "cf_empty": "",
    }
    assert flatten_custom_fields({}) is None
    assert flatten_custom_fields({"custom_fields": []}) is None
