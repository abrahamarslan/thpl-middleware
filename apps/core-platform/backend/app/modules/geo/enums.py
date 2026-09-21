"""Vocabularies for the location hub (docs/geo/README.md).

Every value is stored in a ``text``/``varchar`` column guarded by a CHECK
constraint: the values are data, the closed sets below are the contract.
Telemetry vocabularies (GPS source, motion, anomaly reasons, event types)
deliberately live elsewhere — this module is the address book and its
reference data, not the tracking firehose (README §7).
"""

from __future__ import annotations

import enum


class PlaceKind(str, enum.Enum):
    """What a place *is*. Drives which rules the service applies."""

    ADDRESS = "address"                # a postal address, nothing more
    CUSTOMER_SITE = "customer_site"    # a customer's premises
    HUB = "hub"                        # our own operating hub
    WAREHOUSE = "warehouse"            # stock-holding location (Zoho location)
    OFFICE = "office"
    LANDMARK = "landmark"
    POI = "poi"


class PlaceStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    INVALID = "invalid"                # geocoded to nowhere / known bad


class VerificationStatus(str, enum.Enum):
    """How much we trust the coordinates and the postal text.

    ``GEOCODED_ONLY`` is the trap: a provider returning a point is not
    evidence that a courier can find the door.
    """

    UNVERIFIED = "unverified"
    GEOCODED_ONLY = "geocoded_only"
    FIELD_VERIFIED = "field_verified"
    DISPUTED = "disputed"


class LinkType(str, enum.Enum):
    """WHAT KIND of address a place is *for its owner*.

    The owner's entity class lives in ``owner_type``; this is the semantic the
    classic ``addressable_type`` morph column overloads and gets wrong.
    """

    PRIMARY = "primary"
    BILLING = "billing"
    SHIPPING = "shipping"
    HOME = "home"
    OFFICE = "office"
    SITE = "site"
    CURRENT = "current"          # effective-dated (see SINGLE_VALUED_LINKS)
    PERMANENT = "permanent"      # effective-dated
    OTHER = "other"


#: Link types an owner may hold only ONE of at a time — enforced by the
#: no-overlap EXCLUDE constraint, which also keeps their history.
#: Everything else is many-valued (a customer legitimately ships to ten sites).
SINGLE_VALUED_LINKS = frozenset({LinkType.CURRENT, LinkType.PERMANENT})


class PlaceRelationshipType(str, enum.Enum):
    PARENT_CHILD = "parent_child"
    ROUTE_SEGMENT = "route_segment"
    ADMINISTRATIVE = "administrative"
    GEOFENCE_GROUP = "geofence_group"
    SPATIAL_CLUSTER = "spatial_cluster"


class TransportMode(str, enum.Enum):
    """Distance and duration differ per mode — they are part of the key."""

    DRIVING = "driving"
    TWO_WHEELER = "two_wheeler"
    WALKING = "walking"
    TRUCK = "truck"
    TRANSIT = "transit"


class AdminLevel(str, enum.Enum):
    COUNTRY = "country"
    STATE = "state"
    DISTRICT = "district"
    TALUKA = "taluka"
    CITY = "city"
    LOCALITY = "locality"
    PINCODE = "pincode"
    CONSTITUENCY = "constituency"
    SUB_CONSTITUENCY = "sub_constituency"
    ASSEMBLY_CONSTITUENCY = "assembly_constituency"
    PARLIAMENTARY_CONSTITUENCY = "parliamentary_constituency"


class FenceType(str, enum.Enum):
    PLACE_RADIUS = "place_radius"
    HUB_ZONE = "hub_zone"
    BEAT_AREA = "beat_area"
    RESTRICTED = "restricted"
    CUSTOM = "custom"


class GeoProvider(str, enum.Enum):
    GOOGLE = "google"
    MAPMYINDIA = "mapmyindia"
    OSM_NOMINATIM = "osm_nominatim"
    MANUAL = "manual"


class GeoApiType(str, enum.Enum):
    FORWARD_GEOCODE = "forward_geocode"
    REVERSE_GEOCODE = "reverse_geocode"
    PLACE_DETAILS = "place_details"
    PLACE_AUTOCOMPLETE = "place_autocomplete"
    DIRECTIONS = "directions"
    DISTANCE_MATRIX = "distance_matrix"
    ROADS_SNAP = "roads_snap"
    TIMEZONE = "timezone"
    ADDRESS_VALIDATION = "address_validation"
    ROUTE_OPTIMIZATION = "route_optimization"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum, so the
    constraint and the vocabulary can never drift apart."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


__all__ = [
    "SINGLE_VALUED_LINKS",
    "AdminLevel",
    "FenceType",
    "GeoApiType",
    "GeoProvider",
    "LinkType",
    "PlaceKind",
    "PlaceRelationshipType",
    "PlaceStatus",
    "TransportMode",
    "VerificationStatus",
    "values",
]
