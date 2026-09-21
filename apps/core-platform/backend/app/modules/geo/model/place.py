"""``geo.places`` — the canonical physical place. The WHERE of the platform.

One row per real-world location: a customer's premises, a hub, a warehouse, a
landmark, or a plain postal address. Everything that needs an address points
*here* through ``geo.place_links``; nothing else in the platform stores
coordinates or a postal block of its own.

Design Rule Zero
----------------
A place has no owner, no "visited at", no telemetry. The moment a place
carries ``customer_id`` it stops being reusable, and the same warehouse
address gets written five times with five different spellings. Ownership is a
link (``geo.place_links``), not a column.

The coordinate
--------------
``coordinates`` is the only stored position. ``latitude``, ``longitude`` and
``geohash8`` are GENERATED from it by Postgres and must never be written by
the application — that is what keeps a point and its decimal copy from
disagreeing, which is the classic way an address ends up in two places at
once. ``geohash8`` (≈ 19 m cells) is the near-duplicate probe: two rows
sharing it are almost certainly the same doorway.

Zoho locations
--------------
A Zoho location (warehouse / branch in Zoho Inventory) is projected here as a
place with ``zoho_id`` set and ``kind = 'warehouse'``; ``location_name``,
``is_primary`` and ``parent_location_id`` mirror the Zoho fields so the
hierarchy survives the trip. The mirror table ``zoho_locations`` stays the
record of what Zoho said; this is the usable address.
"""

from __future__ import annotations

import datetime as dt

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    OrgEntityMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.geo.enums import PlaceKind, PlaceStatus, VerificationStatus, values
from app.modules.geo.model.reference import GEO_SCHEMA


class Place(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, Base,
):
    """A canonical geocoded place. The single source of truth for coordinates."""

    __tablename__ = "places"
    __table_args__ = (
        # Target of the composite self-FK below and of place_links' tenant FK.
        UniqueConstraint("tenant_id", "id", name="uq_places_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_location_id"],
            [f"{GEO_SCHEMA}.places.tenant_id", f"{GEO_SCHEMA}.places.id"],
            name="fk_places_parent_location", ondelete="RESTRICT",
        ),
        CheckConstraint(f"kind IN ({values(PlaceKind)})", name="chk_place_kind"),
        CheckConstraint(f"status IN ({values(PlaceStatus)})", name="chk_place_status"),
        CheckConstraint(f"verification_status IN ({values(VerificationStatus)})",
                        name="chk_place_verification_status"),
        CheckConstraint("parent_location_id IS NULL OR parent_location_id <> id",
                        name="chk_place_not_own_parent"),
        CheckConstraint("geocode_confidence IS NULL OR (geocode_confidence >= 0 AND geocode_confidence <= 1)",
                        name="chk_place_geocode_confidence"),
        # One Zoho location maps to exactly one live place per tenant.
        Index("uq_places_zoho_id_live", "tenant_id", "zoho_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        # The same provider place is never stored twice for a tenant.
        Index("uq_places_provider_place_live", "tenant_id", "provider", "provider_place_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND provider_place_id IS NOT NULL")),
        # At most one primary place of a kind per organization.
        Index("uq_places_primary_per_kind", "tenant_id", "organization_id", "kind", unique=True,
              postgresql_where=text("is_primary AND deleted_at IS NULL")),
        # Near-duplicate probe before writing a new place (≈19 m cells).
        Index("ix_places_geohash", "tenant_id", "geohash8",
              postgresql_where=text("geohash8 IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_places_parent_location", "tenant_id", "parent_location_id",
              postgresql_where=text("parent_location_id IS NOT NULL")),
        Index("ix_places_admin_boundary", "admin_boundary_id",
              postgresql_where=text("admin_boundary_id IS NOT NULL")),
        Index("ix_places_postal_code", "tenant_id", "postal_code",
              postgresql_where=text("postal_code IS NOT NULL AND deleted_at IS NULL")),
        # "type three letters of the street" search.
        Index("ix_places_search_trgm", "formatted_address", postgresql_using="gin",
              postgresql_ops={"formatted_address": "gin_trgm_ops"}),
        Index("ix_places_name_trgm", "location_name", postgresql_using="gin",
              postgresql_ops={"location_name": "gin_trgm_ops"}),
        Index("ix_places_custom_attr", "custom_attributes", postgresql_using="gin"),
        {"schema": GEO_SCHEMA,
         "comment": "Canonical physical places — the only table in the platform storing coordinates."},
    )

    # ---- Identity ----------------------------------------------------------
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PlaceKind.ADDRESS.value, server_default=text("'address'"),
        index=True, comment="address / customer_site / hub / warehouse / office / landmark / poi",
    )
    location_name: Mapped[str | None] = mapped_column(
        String(255), comment='Display name — "North Hub", "Acme HQ", the Zoho location name',
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="The organization's primary place of this kind (one, enforced by partial unique)",
    )
    parent_location_id: Mapped[int | None] = mapped_column(
        BigInteger,
        comment="CONTAINMENT only (campus → building → dock). Visit order lives in routes, never here",
    )
    zoho_id: Mapped[str | None] = mapped_column(
        String(50), comment="Zoho location_id when this place mirrors a Zoho location",
    )

    # ---- The coordinate (single source of truth) ---------------------------
    coordinates: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        comment="WGS84 point (longitude, latitude). The only stored coordinate",
    )
    latitude: Mapped[float | None] = mapped_column(
        Numeric(10, 8), Computed("ST_Y(coordinates::geometry)", persisted=True),
        comment="GENERATED from coordinates — never written by the application",
    )
    longitude: Mapped[float | None] = mapped_column(
        Numeric(11, 8), Computed("ST_X(coordinates::geometry)", persisted=True),
        comment="GENERATED from coordinates — never written by the application",
    )
    geohash8: Mapped[str | None] = mapped_column(
        Text, Computed("ST_GeoHash(coordinates::geometry, 8)", persisted=True),
        comment="GENERATED 8-char geohash (≈19 m) — the near-duplicate key",
    )

    # ---- Postal block ------------------------------------------------------
    # Indian addressing is landmark-led: "opposite the water tank" routes a
    # courier where a street number does not. Building / sub-locality /
    # landmark are first-class columns, not a single blob.
    attention: Mapped[str | None] = mapped_column(String(255), comment="Attention / care-of")
    formatted_address: Mapped[str | None] = mapped_column(Text, comment="Full human-readable address")
    building_name: Mapped[str | None] = mapped_column(String(255))
    street: Mapped[str | None] = mapped_column(String(255))
    street2: Mapped[str | None] = mapped_column(String(255))
    landmark: Mapped[str | None] = mapped_column(String(255), comment="Nearby landmark — essential in India")
    sub_locality: Mapped[str | None] = mapped_column(String(255), comment="Colony / sector / area")
    locality: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    district: Mapped[str | None] = mapped_column(String(100))
    taluka: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    state_code: Mapped[str | None] = mapped_column(String(10), comment="GST state code / ISO subdivision")
    postal_code: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(
        String(100), nullable=False, default="India", server_default=text("'India'"),
    )
    country_code: Mapped[str | None] = mapped_column(String(2), comment="ISO 3166-1 alpha-2")
    phone: Mapped[str | None] = mapped_column(String(50))
    fax: Mapped[str | None] = mapped_column(String(50))
    contact_person_name: Mapped[str | None] = mapped_column(String(255))
    contact_email: Mapped[str | None] = mapped_column(String(255))

    # ---- Geocode extract + provenance --------------------------------------
    provider: Mapped[str | None] = mapped_column(String(32), comment="google / mapmyindia / manual …")
    provider_place_id: Mapped[str | None] = mapped_column(
        String(255), comment="Google place_id etc. — storable indefinitely under the licence",
    )
    plus_code: Mapped[str | None] = mapped_column(String(32), comment="Open Location Code")
    place_types: Mapped[list | None] = mapped_column(JSONB, comment='Provider categories ["street_address"]')
    address_components: Mapped[dict | None] = mapped_column(
        JSONB, comment="PARSED components; the raw payload lives once in geocode_api_calls",
    )
    geocode_call_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{GEO_SCHEMA}.geocode_api_calls.id", ondelete="SET NULL",
                   name="fk_places_geocode_call", use_alter=True),
        comment="Provenance: the API call that produced this geocode",
    )
    viewport: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        comment="Provider viewport polygon (replaces four viewport_* decimals)",
    )
    geocode_confidence: Mapped[float | None] = mapped_column(Double, comment="Provider match confidence 0–1")
    geocoded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    # ---- Context -----------------------------------------------------------
    timezone: Mapped[str | None] = mapped_column(String(64), comment="IANA timezone at this point")
    admin_boundary_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{GEO_SCHEMA}.admin_boundaries.id", ondelete="SET NULL", name="fk_places_admin_boundary"),
        comment="Smallest containing admin area (resolved once via ST_Covers, then cached)",
    )
    operating_hours: Mapped[dict | None] = mapped_column(
        JSONB, comment='{"mon": [["09:00","18:00"]], …} — structured, not a free-text string',
    )
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Business extras (dock height, gate code). App-level data goes in app_metadata",
    )

    # No ORM relationship for parent_location: the FK is composite
    # (tenant_id, parent_location_id) and a lazy self-load is exactly the kind
    # of implicit IO an async session forbids. The service walks the tree with
    # explicit queries, as the organization tree does.

    @property
    def is_zoho_linked(self) -> bool:
        return self.zoho_id is not None

    @property
    def has_coordinates(self) -> bool:
        return self.coordinates is not None

    def __repr__(self) -> str:
        return f"<Place id={self.id} kind={self.kind!r} name={self.location_name!r}>"


#: Place columns the Zoho location sync owns — refused on a PATCH of a
#: Zoho-linked place, exactly like the organization rule.
ZOHO_OWNED_PLACE_FIELDS = frozenset({
    "location_name", "is_primary", "parent_location_id", "attention", "street", "street2",
    "city", "state", "state_code", "country", "phone", "contact_email",
})
