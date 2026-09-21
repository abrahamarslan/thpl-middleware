"""The haversine utility. Hermetic — no database, no network."""

import math

import pytest

from app.modules.geo.distance import (
    Direction,
    Unit,
    bearing,
    bounding_box,
    destination,
    distance_m,
    ensure_point,
    haversine,
    normalize,
    within,
)

LYON = (45.7597, 4.8422)
PARIS = (48.8567, 2.3508)
PUNE = (18.5204, 73.8567)
MUMBAI = (19.0760, 72.8777)


def test_known_distance_matches_the_reference_value():
    """The canonical haversine fixture: Lyon → Paris is 392.2 km."""
    assert haversine(LYON, PARIS) == pytest.approx(392.2172595594006, rel=1e-9)
    assert haversine(LYON, PARIS, Unit.METERS) == pytest.approx(392217.2595594006, rel=1e-9)
    assert haversine(LYON, PARIS, Unit.MILES) == pytest.approx(392.2172595594006 * 0.621371192)
    assert distance_m(LYON, PARIS) == pytest.approx(392217.2595594006, rel=1e-9)


def test_every_unit_is_self_consistent():
    km = haversine(PUNE, MUMBAI, Unit.KILOMETERS)
    assert haversine(PUNE, MUMBAI, Unit.METERS) == pytest.approx(km * 1000)
    assert haversine(PUNE, MUMBAI, Unit.FEET) == pytest.approx(km * 3280.839895013)
    radians = haversine(PUNE, MUMBAI, Unit.RADIANS)
    assert haversine(PUNE, MUMBAI, Unit.DEGREES) == pytest.approx(math.degrees(radians))


def test_a_point_is_zero_from_itself():
    assert distance_m(PUNE, PUNE) == pytest.approx(0.0, abs=1e-9)


def test_distance_is_symmetric():
    assert distance_m(PUNE, MUMBAI) == pytest.approx(distance_m(MUMBAI, PUNE))


def test_out_of_range_coordinates_are_refused_not_wrapped():
    """Out-of-range input fails loudly rather than wrapping into the sea.

    Note what this does NOT catch: swapping Pune's (18.52, 73.86) gives
    (73.86, 18.52), and both are legal coordinates — off Norway. A range check
    cannot detect a swap whose latitude happens to be under 90; only a
    plausibility check against the expected country can, which is what
    GEOCODING_DEFAULT_COUNTRY biasing is for.
    """
    with pytest.raises(ValueError, match="latitude"):
        ensure_point(100.0, 20.0)
    with pytest.raises(ValueError, match="longitude"):
        haversine((10.0, 200.0), PUNE)


def test_normalize_wraps_instead_of_raising():
    assert normalize(100.0, 0.0) == pytest.approx((80.0, -180.0))   # over the pole
    assert normalize(0.0, 200.0) == pytest.approx((0.0, -160.0))


def test_bearing_points_the_right_way():
    assert bearing((0.0, 0.0), (10.0, 0.0)) == pytest.approx(0.0, abs=1e-6)     # north
    assert bearing((0.0, 0.0), (0.0, 10.0)) == pytest.approx(90.0, abs=1e-6)    # east
    assert bearing((10.0, 0.0), (0.0, 0.0)) == pytest.approx(180.0, abs=1e-6)   # south
    assert 0.0 <= bearing(PUNE, MUMBAI) < 360.0


def test_destination_is_the_inverse_of_haversine():
    moved = destination(PUNE, 25.0, Direction.NORTH, Unit.KILOMETERS)
    assert haversine(PUNE, moved) == pytest.approx(25.0, rel=1e-9)
    assert moved[0] > PUNE[0]                       # north increases latitude


def test_bounding_box_contains_the_radius_and_is_not_absurd():
    min_lat, min_lng, max_lat, max_lng = bounding_box(PUNE, 1000)
    assert min_lat < PUNE[0] < max_lat and min_lng < PUNE[1] < max_lng
    # A point due north at exactly the radius sits on the box edge.
    edge = destination(PUNE, 1000, Direction.NORTH, Unit.METERS)
    assert edge[0] <= max_lat + 1e-9
    # Longitude degrees are narrower than latitude degrees away from the equator.
    assert (max_lng - min_lng) > (max_lat - min_lat)


def test_bounding_box_survives_the_poles():
    """cos(latitude) → 0 at the pole; the longitude span must not divide by it."""
    min_lat, min_lng, max_lat, max_lng = bounding_box((90.0, 0.0), 5000)
    assert max_lat <= 90.0 and min_lng >= -180.0 and max_lng <= 180.0


def test_within_agrees_with_the_measured_distance():
    near = destination(PUNE, 20, Direction.EAST, Unit.METERS)
    far = destination(PUNE, 500, Direction.EAST, Unit.METERS)
    assert within(PUNE, near, 25) is True
    assert within(PUNE, far, 25) is False
    # The box pre-filter must never reject something inside the radius.
    for degrees in range(0, 360, 15):
        point = destination(PUNE, 24, math.radians(degrees), Unit.METERS)
        assert within(PUNE, point, 25) is True
