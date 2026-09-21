"""Great-circle maths, in process, with no dependencies.

Adapted from the ``haversine`` package (MIT, github.com/mapado/haversine): the
same ``Unit`` vocabulary and kernel, kept in-tree because it is forty lines of
trigonometry and a dependency is a supply chain. Added here: ``bearing``,
``bounding_box`` and metre-first helpers, which the platform needs and the
package does not provide.

**When to use this instead of PostGIS.** PostGIS is the authority: it owns the
stored geometry, the GiST indexes and every query that filters or sorts by
distance (``nearby_places``, ``fences_containing``). Reach for this module
only when there is no round trip to spend — validating input before a write,
scoring candidates already loaded in memory, or computing a straight-line
fallback when no routing provider is configured. Asking the database for the
distance between two numbers you are already holding is a network hop for
arithmetic.

**Accuracy.** The haversine formula assumes a sphere, so it is off by up to
~0.5% against the WGS84 ellipsoid — about 5 m per kilometre, worst case near
the poles. That is immaterial for "is this the same doorway" (25 m) and for a
straight-line estimate; it is *not* good enough for billing by distance or for
legal boundaries. Those go to PostGIS ``ST_Distance`` on geography, which is
ellipsoidal.
"""

from __future__ import annotations

import math
from enum import Enum

#: Mean earth radius — en.wikipedia.org/wiki/Earth_radius#Mean_radius
AVG_EARTH_RADIUS_KM = 6371.0088

Point = tuple[float, float]          #: (latitude, longitude) in decimal degrees


class Unit(str, Enum):
    """Supported units. ``tuple(Unit)`` lists them."""

    KILOMETERS = "km"
    METERS = "m"
    MILES = "mi"
    NAUTICAL_MILES = "nmi"
    FEET = "ft"
    INCHES = "in"
    RADIANS = "rad"
    DEGREES = "deg"


class Direction(float, Enum):
    """Compass directions in radians, for ``destination``."""

    NORTH = 0.0
    NORTHEAST = math.pi * 0.25
    EAST = math.pi * 0.5
    SOUTHEAST = math.pi * 0.75
    SOUTH = math.pi
    SOUTHWEST = math.pi * 1.25
    WEST = math.pi * 1.5
    NORTHWEST = math.pi * 1.75


_CONVERSIONS: dict[Unit, float] = {
    Unit.KILOMETERS: 1.0,
    Unit.METERS: 1000.0,
    Unit.MILES: 0.621371192,
    Unit.NAUTICAL_MILES: 0.539956803,
    Unit.FEET: 3280.839895013,
    Unit.INCHES: 39370.078740158,
    Unit.RADIANS: 1 / AVG_EARTH_RADIUS_KM,
    Unit.DEGREES: (1 / AVG_EARTH_RADIUS_KM) * (180.0 / math.pi),
}


def earth_radius(unit: Unit = Unit.KILOMETERS) -> float:
    return AVG_EARTH_RADIUS_KM * _CONVERSIONS[Unit(unit)]


# ── validation ──────────────────────────────────────────────────────────────

def normalize(latitude: float, longitude: float) -> Point:
    """Wrap a point into [-90, 90] × [-180, 180]."""
    latitude = (latitude + 90) % 360 - 90
    if latitude > 90:
        latitude = 180 - latitude
        longitude += 180
    return latitude, (longitude + 180) % 360 - 180


def ensure_point(latitude: float, longitude: float) -> Point:
    """Raise unless the point is already in range. Used at the API edge, where
    a swapped latitude/longitude pair is the single most common mistake — and
    silently wrapping it would put the address in the sea instead of failing."""
    if not -90 <= latitude <= 90:
        raise ValueError(f"latitude {latitude} is out of range [-90, 90]")
    if not -180 <= longitude <= 180:
        raise ValueError(f"longitude {longitude} is out of range [-180, 180]")
    return latitude, longitude


# ── the kernel ──────────────────────────────────────────────────────────────

def _haversine_radians(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance on the unit sphere, in radians. Degrees in."""
    lat1, lng1, lat2, lng2 = map(math.radians, (lat1, lng1, lat2, lng2))
    d = (
        math.sin((lat2 - lat1) * 0.5) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) * 0.5) ** 2
    )
    # 2 * atan2(sqrt(d), sqrt(1-d)) is more accurate for antipodal points and
    # slower; asin is plenty for the distances this platform deals in.
    return 2 * math.asin(math.sqrt(min(1.0, d)))


def haversine(
    point1: Point, point2: Point, unit: Unit = Unit.KILOMETERS, *,
    normalize_points: bool = False, check: bool = True,
) -> float:
    """Great-circle distance between two ``(latitude, longitude)`` pairs.

    >>> round(haversine((45.7597, 4.8422), (48.8567, 2.3508), Unit.METERS))
    392217
    """
    lat1, lng1 = point1
    lat2, lng2 = point2
    if normalize_points:
        lat1, lng1 = normalize(lat1, lng1)
        lat2, lng2 = normalize(lat2, lng2)
    elif check:
        ensure_point(lat1, lng1)
        ensure_point(lat2, lng2)
    return earth_radius(unit) * _haversine_radians(lat1, lng1, lat2, lng2)


def distance_m(point1: Point, point2: Point) -> float:
    """Metres — the unit every distance column in this platform uses."""
    return haversine(point1, point2, Unit.METERS)


def bearing(point1: Point, point2: Point) -> float:
    """Initial compass bearing from point1 to point2, degrees clockwise from
    north (0–360). Matches PostGIS ``degrees(ST_Azimuth(...))``."""
    lat1, lng1 = map(math.radians, ensure_point(*point1))
    lat2, lng2 = map(math.radians, ensure_point(*point2))
    delta = lng2 - lng1
    theta = math.atan2(
        math.sin(delta) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta),
    )
    return math.degrees(theta) % 360


def destination(
    point: Point, distance: float, direction: Direction | float,
    unit: Unit = Unit.KILOMETERS, *, normalize_output: bool = False,
) -> Point:
    """The point reached by travelling ``distance`` from ``point`` along
    ``direction`` (radians). The inverse of ``haversine``."""
    lat, lng = map(math.radians, point)
    d = distance / earth_radius(unit)
    cos_d, sin_d = math.cos(d), math.sin(d)
    cos_lat, sin_lat = math.cos(lat), math.sin(lat)
    sin_d_cos_lat = sin_d * cos_lat

    out_lat = math.asin(cos_d * sin_lat + sin_d_cos_lat * math.cos(direction))
    out_lng = lng + math.atan2(
        math.sin(direction) * sin_d_cos_lat, cos_d - sin_lat * math.sin(out_lat)
    )
    result = (math.degrees(out_lat), math.degrees(out_lng))
    return normalize(*result) if normalize_output else result


def bounding_box(point: Point, radius_m: float) -> tuple[float, float, float, float]:
    """``(min_lat, min_lng, max_lat, max_lng)`` enclosing a radius.

    A cheap pre-filter: a box comparison is four numeric tests, where a true
    distance is trigonometry. Useful for narrowing an in-memory candidate list
    before measuring, and for handing a viewport to a geocoding provider so it
    biases results towards where we already know the address is.
    """
    lat, lng = ensure_point(*point)
    lat_delta = math.degrees(radius_m / (AVG_EARTH_RADIUS_KM * 1000.0))
    # Longitude degrees shrink towards the poles; guard the division at ±90.
    cos_lat = math.cos(math.radians(lat))
    lng_delta = 180.0 if abs(cos_lat) < 1e-12 else lat_delta / cos_lat
    return (
        max(-90.0, lat - lat_delta), max(-180.0, lng - lng_delta),
        min(90.0, lat + lat_delta), min(180.0, lng + lng_delta),
    )


def within(point1: Point, point2: Point, radius_m: float) -> bool:
    """Is point2 within ``radius_m`` of point1? Box test first, then exact."""
    min_lat, min_lng, max_lat, max_lng = bounding_box(point1, radius_m)
    lat, lng = point2
    if not (min_lat <= lat <= max_lat and min_lng <= lng <= max_lng):
        return False
    return distance_m(point1, point2) <= radius_m


__all__ = [
    "AVG_EARTH_RADIUS_KM",
    "Direction",
    "Point",
    "Unit",
    "bearing",
    "bounding_box",
    "destination",
    "distance_m",
    "earth_radius",
    "ensure_point",
    "haversine",
    "normalize",
    "within",
]
