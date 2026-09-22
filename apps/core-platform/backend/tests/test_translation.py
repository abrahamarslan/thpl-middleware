"""The translation layer: the anti-corruption boundary, in both directions.

These are pure tests — no database, no HTTP. The whole point of pulling
translation out of the engine is that "what does this Zoho field mean here"
becomes answerable without standing anything up.

The payloads are the documented ones from docs/zoho-docs-md/currency.md.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.currencies.zoho.translator import (
    CURRENCY_TRANSLATOR,
    ZOHO_OWNED_CURRENCY_FIELDS,
)
from app.modules.sync.translation import (
    CODECS,
    Decoded,
    Direction,
    FieldSpec,
    FieldTranslator,
    PayloadShape,
    TranslationError,
    WriteIntent,
)

# The documented list row (docs/zoho-docs-md/currency.md, "List Currencies").
LIST_ROW = {
    "currency_id": "982000000004012",
    "currency_code": "AUD",
    "currency_name": "AUD- Australian Dollar",
    "currency_symbol": "$",
    "price_precision": 2,
    "currency_format": "1,234,567.89",
    "is_base_currency": False,
    "exchange_rate": 1,
    "effective_date": "2013-09-04",
}


def _currency(**kw) -> SimpleNamespace:
    base = dict(currency_code="AUD", currency_format="1,234,567.89", currency_symbol="$",
                price_precision=2, currency_name="AUD- Australian Dollar",
                is_base_currency=False, exchange_rate=Decimal("1"), effective_date=date(2013, 9, 4))
    return SimpleNamespace(**{**base, **kw})


# ── inbound ─────────────────────────────────────────────────────────────────

def test_a_list_row_decodes_into_canonical_columns():
    decoded = CURRENCY_TRANSLATOR.decode(LIST_ROW, shape=PayloadShape.INDEX)

    assert decoded.values["currency_code"] == "AUD"
    assert decoded.values["currency_name"] == "AUD- Australian Dollar"
    assert decoded.values["price_precision"] == 2
    assert decoded.values["is_base_currency"] is False
    assert decoded.values["exchange_rate"] == Decimal("1")
    assert decoded.values["effective_date"] == date(2013, 9, 4)
    assert not decoded.warnings


def test_the_source_id_is_not_a_canonical_column():
    """Identity belongs to the crosswalk; decoding must not smuggle it back."""
    decoded = CURRENCY_TRANSLATOR.decode(LIST_ROW)
    assert "currency_id" not in decoded.values
    assert "zoho_id" not in decoded.values


def test_a_missing_key_is_skipped_not_decoded_to_null():
    """A thin payload must never erase a column a richer one filled."""
    thin = {"currency_id": "1", "currency_code": "AUD"}
    decoded = CURRENCY_TRANSLATOR.decode(thin, shape=PayloadShape.INDEX)
    assert decoded.values == {"currency_code": "AUD"}
    assert "currency_name" not in decoded.values


def test_a_present_but_null_value_is_honoured():
    decoded = CURRENCY_TRANSLATOR.decode({**LIST_ROW, "currency_symbol": None})
    assert decoded.values["currency_symbol"] is None


def test_a_bad_value_is_reported_not_raised():
    """One malformed attribute must not cost us the whole record."""
    decoded = CURRENCY_TRANSLATOR.decode({**LIST_ROW, "exchange_rate": "not-a-number"})
    assert "exchange_rate" not in decoded.values
    assert any("exchange_rate" in w for w in decoded.warnings)
    assert decoded.values["currency_code"] == "AUD", "the rest of the record survived"


def test_the_inline_rate_becomes_a_child_row():
    decoded = CURRENCY_TRANSLATOR.decode(LIST_ROW)
    assert decoded.children["exchange_rates"] == [
        {"rate": Decimal("1"), "effective_date": date(2013, 9, 4), "rate_source": "zoho"}
    ]


def test_a_currency_without_a_rate_produces_no_child_row():
    """A rate row with no rate would read as a real quote of zero."""
    payload = {k: v for k, v in LIST_ROW.items() if k != "exchange_rate"}
    assert CURRENCY_TRANSLATOR.decode(payload).children == {}


def test_a_rates_collection_decodes():
    rows = CURRENCY_TRANSLATOR.decode_rates([
        {"exchange_rate_id": "77", "rate": "1.23", "effective_date": "2013-09-04"},
        {"exchange_rate_id": "78", "rate": None, "effective_date": "2013-09-05"},
    ])
    assert rows == [{"rate": Decimal("1.23"), "effective_date": date(2013, 9, 4),
                     "rate_source": "zoho"}]


# ── outbound: never the inverted decoder ────────────────────────────────────

def test_read_only_fields_are_never_sent_back():
    """Zoho computes currency_name and derives is_base_currency; the rate is
    written through its own endpoint. A symmetric map would send all three."""
    payload = CURRENCY_TRANSLATOR.encode(_currency(), intent=WriteIntent.CREATE)

    assert set(payload) == {"currency_code", "currency_format", "currency_symbol", "price_precision"}
    for read_only in ("currency_name", "is_base_currency", "exchange_rate",
                      "effective_date", "currency_id"):
        assert read_only not in payload


def test_a_create_payload_matches_the_documented_arguments():
    payload = CURRENCY_TRANSLATOR.encode(_currency(), intent=WriteIntent.CREATE)
    assert payload == {
        "currency_code": "AUD",
        "currency_symbol": "$",
        "price_precision": 2,
        "currency_format": "1,234,567.89",
    }


def test_a_create_without_a_required_argument_is_refused_before_the_call():
    with pytest.raises(TranslationError) as excinfo:
        CURRENCY_TRANSLATOR.encode(_currency(currency_format=None), intent=WriteIntent.CREATE)
    assert "currency_format" in str(excinfo.value)


def test_an_update_does_not_demand_the_create_arguments():
    payload = CURRENCY_TRANSLATOR.encode(_currency(currency_format=None), intent=WriteIntent.UPDATE)
    assert payload == {"currency_code": "AUD", "currency_symbol": "$", "price_precision": 2}


def test_none_values_are_omitted_rather_than_sent_as_null():
    payload = CURRENCY_TRANSLATOR.encode(_currency(currency_symbol=None), intent=WriteIntent.UPDATE)
    assert "currency_symbol" not in payload


def test_a_rate_encodes_as_a_json_number():
    body = CURRENCY_TRANSLATOR.encode_rate(
        SimpleNamespace(rate=Decimal("1.23"), effective_date=date(2013, 9, 4)),
        intent=WriteIntent.CREATE,
    )
    assert body == {"rate": 1.23, "effective_date": "2013-09-04"}
    assert isinstance(body["rate"], float), "Zoho documents rate as a double"


def test_a_whole_rate_encodes_without_a_float_tail():
    body = CURRENCY_TRANSLATOR.encode_rate(
        SimpleNamespace(rate=Decimal("2"), effective_date=None), intent=WriteIntent.CREATE
    )
    assert body == {"rate": 2} and isinstance(body["rate"], int)


# ── round trip ──────────────────────────────────────────────────────────────

def test_decode_then_encode_preserves_the_writable_fields():
    """The writable subset survives the round trip; the read-only rest is dropped
    on purpose, which is why this is not an equality check against the payload."""
    decoded = CURRENCY_TRANSLATOR.decode(LIST_ROW)
    entity = SimpleNamespace(**decoded.values)
    payload = CURRENCY_TRANSLATOR.encode(entity, intent=WriteIntent.CREATE)

    for field in ("currency_code", "currency_symbol", "price_precision", "currency_format"):
        assert payload[field] == LIST_ROW[field]


# ── the spec vocabulary ─────────────────────────────────────────────────────

def test_owned_fields_are_derived_from_the_field_rules():
    """Hand-listing them is how they drift from what the sync actually writes."""
    assert "currency_name" in ZOHO_OWNED_CURRENCY_FIELDS
    assert "exchange_rate" in ZOHO_OWNED_CURRENCY_FIELDS
    assert ZOHO_OWNED_CURRENCY_FIELDS == frozenset(CURRENCY_TRANSLATOR.readable)


def test_legacy_keyword_spellings_still_build_a_spec():
    """Four existing modules declare maps in the old vocabulary."""
    legacy = FieldSpec(zoho="a.b", local="col", transform="str", outbound=False)
    assert legacy.external == "a.b" and legacy.codec == "str"
    assert legacy.direction is Direction.IN
    assert legacy.reads and not legacy.writes


def test_a_write_key_may_differ_from_the_read_key():
    spec = FieldSpec(external="read_name", local="col", external_write="write_name")
    translator = FieldTranslator("t", [spec])
    assert translator.decode({"read_name": "v"}).values == {"col": "v"}
    assert translator.encode(SimpleNamespace(col="v")) == {"write_name": "v"}


def test_dotted_paths_nest_on_the_way_out():
    spec = FieldSpec(external="address.city", local="city")
    translator = FieldTranslator("t", [spec])
    assert translator.decode({"address": {"city": "Pune"}}).values == {"city": "Pune"}
    assert translator.encode(SimpleNamespace(city="Pune")) == {"address": {"city": "Pune"}}


def test_an_unknown_codec_degrades_to_passthrough_and_says_so():
    translator = FieldTranslator("t", [FieldSpec(external="x", local="x", codec="nope")])
    assert translator.decode({"x": "raw"}).values == {"x": "raw"}


@pytest.mark.parametrize("name", ["str", "int", "bool", "decimal", "money",
                                  "zoho_date", "zoho_datetime", "passthrough"])
def test_every_codec_handles_none_in_both_directions(name):
    codec = CODECS[name]
    assert codec.decode(None) is None
    assert codec.encode(None) is None


def test_payload_shape_is_read_from_the_engines_provenance_string():
    assert PayloadShape.of("list:full") is PayloadShape.INDEX
    assert PayloadShape.of("detail_fetch") is PayloadShape.DETAIL
    assert PayloadShape.of("nested:contacts") is PayloadShape.NESTED
    assert PayloadShape.of("webhook") is PayloadShape.WEBHOOK
    assert PayloadShape.of(None) is PayloadShape.INDEX


def test_decoded_defaults_are_independent():
    assert Decoded().values == {} and Decoded().children == {}
    first = Decoded()
    first.values["a"] = 1
    assert Decoded().values == {}
