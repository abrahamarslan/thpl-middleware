"""Location hub models (schema ``geo``) — see docs/geo/README.md.

    reference   AdminBoundary   administrative areas (global reference data)
                Geofence        tenant-drawn zones with an entry/exit policy
    provenance  GeocodeApiCall  every external geo-API payload, stored once
    places      Place           THE canonical physical place
    links       PlaceLink       any entity ↔ a place (the address book)
                PlaceRelationship   place ↔ place, with per-mode metrics

Import order matters: ``place`` declares a composite self-FK and a cyclic FK
to ``geocode_api_calls`` (``use_alter``), so both tables must be in the
metadata before the mappers configure.
"""

from app.modules.geo.model.geocode import GeocodeApiCall
from app.modules.geo.model.link import OWNER_TYPES, PlaceLink, PlaceRelationship
from app.modules.geo.model.place import ZOHO_OWNED_PLACE_FIELDS, Place
from app.modules.geo.model.reference import GEO_SCHEMA, AdminBoundary, Geofence

__all__ = [
    "GEO_SCHEMA",
    "OWNER_TYPES",
    "ZOHO_OWNED_PLACE_FIELDS",
    "AdminBoundary",
    "GeocodeApiCall",
    "Geofence",
    "Place",
    "PlaceLink",
    "PlaceRelationship",
]
