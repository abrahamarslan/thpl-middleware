"""Provider parsers, against saved payloads. No network, no database.

This is what the build/parse split buys: every provider's translation into
our postal columns is testable as a pure function. All four are given the
same Pune address so the normalization can be compared side by side — which
is the only way to notice that one of them quietly drops the district.
"""

import pytest

from app.core.conf import settings
from app.modules.geo.enums import GeoApiType
from app.modules.geo.geocoding.providers import (
    GoogleGeocoder,
    MapboxGeocoder,
    NominatimGeocoder,
    PeliasGeocoder,
    ValhallaRouting,
)

FORWARD = GeoApiType.FORWARD_GEOCODE

GOOGLE_PAYLOAD = {
    "status": "OK",
    "results": [{
        "address_components": [
            {"long_name": "12", "short_name": "12", "types": ["street_number"]},
            {"long_name": "Mahatma Gandhi Road", "short_name": "MG Rd", "types": ["route"]},
            {"long_name": "Camp", "short_name": "Camp",
             "types": ["sublocality_level_1", "sublocality", "political"]},
            {"long_name": "Pune", "short_name": "Pune", "types": ["locality", "political"]},
            {"long_name": "Pune Division", "short_name": "Pune Division",
             "types": ["administrative_area_level_2", "political"]},
            {"long_name": "Maharashtra", "short_name": "MH",
             "types": ["administrative_area_level_1", "political"]},
            {"long_name": "India", "short_name": "IN", "types": ["country", "political"]},
            {"long_name": "411001", "short_name": "411001", "types": ["postal_code"]},
        ],
        "formatted_address": "12, Mahatma Gandhi Rd, Camp, Pune, Maharashtra 411001, India",
        "geometry": {
            "location": {"lat": 18.5204, "lng": 73.8567},
            "location_type": "ROOFTOP",
            "viewport": {"northeast": {"lat": 18.5218, "lng": 73.8581},
                         "southwest": {"lat": 18.5191, "lng": 73.8554}},
        },
        "place_id": "ChIJ_PuneMGRoad",
        "types": ["street_address"],
        "plus_code": {"global_code": "7JCWGRM4+2X"},
    }],
}

MAPBOX_V6_PAYLOAD = {
    "features": [{
        "type": "Feature",
        "properties": {
            "mapbox_id": "dXJuOm1ieGFkZHI6MTIz",
            "feature_type": "address",
            "name": "12 Mahatma Gandhi Road",
            "full_address": "12 Mahatma Gandhi Road, Pune, Maharashtra 411001, India",
            "coordinates": {"longitude": 73.8567, "latitude": 18.5204},
            "match_code": {"confidence": "high"},
            "context": {
                "street": {"name": "Mahatma Gandhi Road"},
                "neighborhood": {"name": "Camp"},
                "postcode": {"name": "411001"},
                "place": {"name": "Pune"},
                "district": {"name": "Pune Division"},
                "region": {"name": "Maharashtra", "region_code": "MH"},
                "country": {"name": "India", "country_code": "IN"},
            },
        },
    }],
}

MAPBOX_V5_PAYLOAD = {
    "features": [{
        "id": "address.8675309",
        "place_name": "12 Mahatma Gandhi Road, Pune, Maharashtra 411001, India",
        "relevance": 0.95,
        "center": [73.8567, 18.5204],
        "place_type": ["address"],
        "text": "Mahatma Gandhi Road",
        "address": "12",
        "context": [
            {"id": "neighborhood.1", "text": "Camp"},
            {"id": "postcode.2", "text": "411001"},
            {"id": "place.3", "text": "Pune"},
            {"id": "district.4", "text": "Pune Division"},
            {"id": "region.5", "text": "Maharashtra", "short_code": "IN-MH"},
            {"id": "country.6", "text": "India", "short_code": "in"},
        ],
    }],
}

NOMINATIM_PAYLOAD = [{
    "place_id": 123456,
    "osm_type": "way",
    "osm_id": 987654,
    "lat": "18.5204",
    "lon": "73.8567",
    "display_name": "12, Mahatma Gandhi Road, Camp, Pune, Pune Division, Maharashtra, 411001, India",
    "category": "building",
    "type": "commercial",
    "importance": 0.42,
    "boundingbox": ["18.5191", "18.5218", "73.8554", "73.8581"],
    "address": {
        "house_number": "12", "road": "Mahatma Gandhi Road", "suburb": "Camp",
        "city": "Pune", "state_district": "Pune Division", "state": "Maharashtra",
        "ISO3166-2-lvl4": "IN-MH", "postcode": "411001",
        "country": "India", "country_code": "in",
    },
}]

PELIAS_PAYLOAD = {
    "features": [{
        "geometry": {"type": "Point", "coordinates": [73.8567, 18.5204]},
        "bbox": [73.8554, 18.5191, 73.8581, 18.5218],
        "properties": {
            "gid": "openstreetmap:address:way/987654",
            "layer": "address",
            "name": "12 Mahatma Gandhi Road",
            "housenumber": "12",
            "street": "Mahatma Gandhi Road",
            "neighbourhood": "Camp",
            "locality": "Pune",
            "localadmin": "Pune",
            "county": "Pune Division",
            "region": "Maharashtra",
            "region_a": "MH",
            "postalcode": "411001",
            "country": "India",
            "country_a": "IND",
            "confidence": 0.9,
            "label": "12 Mahatma Gandhi Road, Pune, India",
        },
    }],
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-google-key", raising=False)
    monkeypatch.setattr(settings, "MAPBOX_ACCESS_TOKEN", "test-mapbox-token", raising=False)
    monkeypatch.setattr(settings, "GEOCODING_NOMINATIM_USER_AGENT", "th-middleware/test", raising=False)
    monkeypatch.setattr(settings, "GEOCODING_PELIAS_BASE_URL", "http://pelias.internal:4000", raising=False)
    monkeypatch.setattr(settings, "ROUTING_VALHALLA_BASE_URL", "http://valhalla.internal:8002", raising=False)
    monkeypatch.setattr(settings, "GEOCODING_MAPBOX_BASE_URL", "", raising=False)
    return settings


@pytest.mark.parametrize(
    ("provider_cls", "payload"),
    [
        (GoogleGeocoder, GOOGLE_PAYLOAD),
        (MapboxGeocoder, MAPBOX_V6_PAYLOAD),
        (MapboxGeocoder, MAPBOX_V5_PAYLOAD),
        (NominatimGeocoder, NOMINATIM_PAYLOAD),
        (PeliasGeocoder, PELIAS_PAYLOAD),
    ],
)
def test_every_provider_normalizes_to_the_same_address(provider_cls, payload, configured):
    """Four upstreams, four taxonomies, one set of columns."""
    result = provider_cls(configured).parse(payload, FORWARD)[0]

    assert result.latitude == pytest.approx(18.5204)
    assert result.longitude == pytest.approx(73.8567)
    assert result.provider_place_id
    assert result.formatted_address

    components = result.components
    assert components["street"] == "12 Mahatma Gandhi Road"
    assert components["sub_locality"] == "Camp"
    assert components["city"] == "Pune"
    assert components["district"] == "Pune Division"
    assert components["state"] == "Maharashtra"
    assert components["state_code"] == "MH"
    assert components["postal_code"] == "411001"
    assert components["country"] == "India"
    assert components["country_code"] == "IN"


def test_confidence_is_normalized_to_a_fraction(configured):
    google = GoogleGeocoder(configured).parse(GOOGLE_PAYLOAD, FORWARD)[0]
    mapbox = MapboxGeocoder(configured).parse(MAPBOX_V6_PAYLOAD, FORWARD)[0]
    pelias = PeliasGeocoder(configured).parse(PELIAS_PAYLOAD, FORWARD)[0]

    assert google.confidence == 1.0                    # ROOFTOP
    for result in (google, mapbox, pelias):
        assert 0.0 <= result.confidence <= 1.0


def test_a_viewport_comes_back_as_lng_lat_bounds(configured):
    for provider_cls, payload in (
        (GoogleGeocoder, GOOGLE_PAYLOAD), (NominatimGeocoder, NOMINATIM_PAYLOAD),
        (PeliasGeocoder, PELIAS_PAYLOAD),
    ):
        min_lng, min_lat, max_lng, max_lat = provider_cls(configured).parse(payload, FORWARD)[0].viewport
        assert min_lng < max_lng and min_lat < max_lat
        assert 73 < min_lng < 74 and 18 < min_lat < 19


def test_place_values_map_onto_place_columns(configured):
    """Whatever a provider returns must be writable onto geo.places."""
    from app.modules.geo.model import Place

    values = GoogleGeocoder(configured).parse(GOOGLE_PAYLOAD, FORWARD)[0].place_values()
    columns = set(Place.__table__.c.keys())
    assert set(values) <= columns, f"not columns of geo.places: {sorted(set(values) - columns)}"


# ── credentials and failure signalling ──────────────────────────────────────

def test_api_keys_never_reach_the_cache_key(configured):
    """``cache_params`` is hashed AND stored; a key in it is a leaked key."""
    from app.modules.geo.geocoding.types import GeoQuery, ReverseQuery

    query = GeoQuery(text="12 MG Road, Pune", country="IN")
    for provider_cls in (GoogleGeocoder, MapboxGeocoder, NominatimGeocoder, PeliasGeocoder):
        provider = provider_cls(configured)
        for request in (provider.build_forward(query),
                        provider.build_reverse(ReverseQuery(18.5204, 73.8567))):
            serialized = str(request.cache_params).lower()
            assert "test-google-key" not in serialized
            assert "test-mapbox-token" not in serialized
            for secret in ("key", "access_token", "api_key"):
                assert secret not in request.cache_params


def test_google_200_with_request_denied_is_a_rejection(configured):
    """The trap: HTTP 200 carrying a fatal provider status."""
    provider = GoogleGeocoder(configured)
    denied = {"status": "REQUEST_DENIED", "error_message": "The provided API key is invalid."}

    status = provider.check_payload(denied)
    assert status == "REQUEST_DENIED" and provider.is_rejection(status) is True
    assert provider.parse(denied, FORWARD) == []


def test_zero_results_is_an_answer_not_a_fault(configured):
    provider = GoogleGeocoder(configured)
    assert provider.check_payload({"status": "ZERO_RESULTS", "results": []}) is None


def test_google_throttling_is_retryable_but_a_dead_key_is_not(configured):
    provider = GoogleGeocoder(configured)
    assert provider.is_rejection("OVER_QUERY_LIMIT") is False      # per-second, try again
    assert provider.is_rejection("OVER_DAILY_LIMIT") is True       # the account is out


def test_nominatim_sends_a_user_agent(configured):
    """The public instance rejects anonymous traffic outright."""
    from app.modules.geo.geocoding.types import GeoQuery

    request = NominatimGeocoder(configured).build_forward(GeoQuery(text="Pune"))
    assert request.headers["User-Agent"] == "th-middleware/test"


def test_a_missing_key_is_reported_by_name_not_value():
    from app.core.conf import settings as live

    provider = GoogleGeocoder(live)
    if not live.GOOGLE_MAPS_API_KEY:
        assert provider.missing_settings() == ["GOOGLE_MAPS_API_KEY"]


# ── routing ─────────────────────────────────────────────────────────────────

def test_valhalla_matrix_is_converted_to_metres(configured):
    payload = {
        "sources_to_targets": [[{"distance": 12.5, "time": 1500, "from_index": 0, "to_index": 0}]],
        "units": "kilometers",
    }
    leg = ValhallaRouting(configured).parse_matrix(payload, "driving")[0][0]
    assert leg.distance_m == pytest.approx(12500.0)
    assert leg.duration_s == pytest.approx(1500.0)
    assert leg.provider == "valhalla"


def test_valhalla_gets_our_mode_translated(configured):
    request = ValhallaRouting(configured).build_matrix([(18.52, 73.85)], [(19.07, 72.87)], "two_wheeler")
    assert request.json_body["costing"] == "motor_scooter"
    assert request.method == "POST"
    assert request.url.endswith("/sources_to_targets")


def test_an_unreachable_pair_is_dropped_not_reported_as_zero(configured):
    payload = {"sources_to_targets": [[{"distance": None, "time": None}]], "units": "kilometers"}
    assert ValhallaRouting(configured).parse_matrix(payload, "driving") == [[]]
