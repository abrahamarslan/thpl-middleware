"""``geo.place_links`` — the polymorphic address book, and ``geo.place_relationships``.

PlaceLink
=========
The answer to "where is this thing?", for any thing: a customer, a contact
person, an invoice, an estimate, a warehouse, a user. ``owner_type`` +
``owner_id`` name the owner; ``place_id`` names the place; ``link_type`` says
what kind of address it is *for that owner* (billing, shipping, home, …).

Two columns that are usually conflated, kept apart on purpose:

* ``owner_type`` — WHO owns the link (the entity class).
* ``link_type``  — WHAT KIND of address it is for them.

A single morph column carrying both is how "shipping" ends up as an entity
class, and why nobody can then answer "every billing address in the tenant".

**One link table, not two.** The reference design this module is built from
splits effective-dated postal addresses from operational place links. Here
they are the same shape — owner, place, type, primary flag, validity window —
and two tables of that shape mean every reader has to ask which one a
customer's billing address is in. The split earns its keep only where a
personnel/KYC contract differs from an operational one; this platform has no
such contract, so the temporal machinery lives on the one table and applies
to the link types that are genuinely single-valued
(``enums.SINGLE_VALUED_LINKS``).

**Snapshots.** An invoice's billing address must read the same in five years
even if the customer moves. Linking with a snapshot freezes the formatted
address and the postal block into ``snapshot`` at link time; the live place
keeps changing beside it. Contacts link live, documents link frozen.

**Detaching** is a soft delete: ``deleted_at`` / ``deleted_by`` /
``deleted_reason`` already say who unlinked it, when and why, so there are no
separate ``detached_*`` columns to keep in step.

PlaceRelationship
=================
Place ↔ place, with metrics per transport mode — a two-wheeler and a truck do
not share a distance between the same two gates, so the mode is part of the
key. Metrics are computed at WRITE time; the classic trigger that recomputed
them with correlated subqueries on every row is not repeated here.
"""

from __future__ import annotations

import datetime as dt

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    OrgEntityMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.geo.enums import (
    LinkType,
    PlaceRelationshipType,
    TransportMode,
    VerificationStatus,
    values,
)
from app.modules.geo.model.place import Place
from app.modules.geo.model.reference import GEO_SCHEMA

#: Entity classes that may own an address. A closed set, because an open one
#: becomes a graveyard of typos ('Customer', 'customers', 'customer').
#: Phase 6 modules (contacts, invoices, estimates) add their names here.
OWNER_TYPES: tuple[str, ...] = (
    "user",
    "organization",
    "customer",
    "contact_person",
    "vendor",
    "warehouse",
    "zoho_location",
    "invoice",
    "estimate",
    "sales_order",
    "purchase_order",
    "shipment",
)

_OWNER_TYPE_SQL = ",".join(f"'{name}'" for name in OWNER_TYPES)
#: Link types whose windows may not overlap for one owner (enums.SINGLE_VALUED_LINKS).
_SINGLE_VALUED_SQL = "'current','permanent'"


class PlaceLink(
    BigIntPKWithUUIDMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, Base,
):
    """An address of an entity: owner ↔ place, typed, dated, optionally frozen."""

    __tablename__ = "place_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "place_id"],
            [f"{GEO_SCHEMA}.places.tenant_id", f"{GEO_SCHEMA}.places.id"],
            name="fk_place_links_tenant_place", ondelete="RESTRICT",
        ),
        CheckConstraint(f"owner_type IN ({_OWNER_TYPE_SQL})", name="chk_place_link_owner_type"),
        CheckConstraint(f"link_type IN ({values(LinkType)})", name="chk_place_link_type"),
        CheckConstraint(f"verification_status IN ({values(VerificationStatus)})",
                        name="chk_place_link_verification_status"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_place_link_status"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_place_link_validity"),
        CheckConstraint("owner_id > 0", name="chk_place_link_owner_id"),
        # The same place is not attached twice to an owner for the same purpose.
        Index("uq_place_links_dedupe", "tenant_id", "owner_type", "owner_id", "place_id",
              "link_type", "purpose", unique=True, postgresql_where=text("deleted_at IS NULL")),
        # One open primary per owner and link type.
        Index("uq_place_links_one_primary", "tenant_id", "owner_type", "owner_id", "link_type",
              unique=True,
              postgresql_where=text("is_primary AND valid_to IS NULL AND deleted_at IS NULL")),
        # Single-valued types (current / permanent) keep a history but may
        # never overlap in time. Needs btree_gist for the '=' operators.
        ExcludeConstraint(
            ("tenant_id", "="), ("owner_type", "="), ("owner_id", "="), ("link_type", "="),
            (text("tstzrange(valid_from, valid_to)"), "&&"),
            using="gist",
            where=text(f"deleted_at IS NULL AND link_type IN ({_SINGLE_VALUED_SQL})"),
            name="place_links_no_overlap",
        ),
        # THE read path: "give me this customer's addresses".
        Index("ix_place_links_owner", "tenant_id", "owner_type", "owner_id", "link_type",
              postgresql_where=text("deleted_at IS NULL")),
        # The reverse: "who uses this place?" — needed before archiving one.
        Index("ix_place_links_place", "place_id", postgresql_where=text("deleted_at IS NULL")),
        {"schema": GEO_SCHEMA, "comment": "Polymorphic address book: any entity ↔ a canonical place."},
    )

    place_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="The place this address points at")
    owner_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Owning entity class — WHO owns the link",
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Owning entity id")
    link_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=LinkType.PRIMARY.value, server_default=text("'primary'"),
        comment="WHAT KIND of address it is for the owner",
    )
    purpose: Mapped[str] = mapped_column(
        String(50), nullable=False, default="", server_default=text("''"),
        comment="Operational use (delivery, invoice, returns). '' = none; NOT NULL so it can key a unique index",
    )
    label: Mapped[str | None] = mapped_column(String(100), comment='User-facing label: "Head office", "Factory"')
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )

    # ---- Per-link overrides (the place stays canonical) --------------------
    attention: Mapped[str | None] = mapped_column(
        String(255), comment="Who to ask for at this place, for this owner",
    )
    landmark: Mapped[str | None] = mapped_column(String(255), comment="Courier note overriding the place landmark")
    delivery_instructions: Mapped[str | None] = mapped_column(String(500))
    contact_phone: Mapped[str | None] = mapped_column(String(50))

    # ---- Effective dating --------------------------------------------------
    valid_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    valid_to: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="NULL = still current; an address change closes the old row",
    )

    # ---- Frozen copy for documents ----------------------------------------
    snapshot: Mapped[dict | None] = mapped_column(
        JSONB,
        comment="The address as printed when it was linked. Set for documents; "
                "NULL means the link follows the live place",
    )
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    place: Mapped[Place] = relationship(
        Place, primaryjoin="foreign(PlaceLink.place_id) == Place.id", viewonly=True, lazy="raise",
    )

    @property
    def is_current(self) -> bool:
        return self.valid_to is None and self.deleted_at is None

    @property
    def is_frozen(self) -> bool:
        return self.snapshot is not None

    def close(self, at: dt.datetime | None = None) -> None:
        """End the validity window — the way an address is superseded."""
        self.valid_to = at or dt.datetime.now(dt.UTC)
        self.is_primary = False

    def __repr__(self) -> str:
        return (
            f"<PlaceLink id={self.id} {self.owner_type}:{self.owner_id} "
            f"→ place {self.place_id} ({self.link_type})>"
        )


class PlaceRelationship(
    BigIntPKWithUUIDMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base,
):
    """A relation between two places, with routing metrics per transport mode."""

    __tablename__ = "place_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "place_id"],
            [f"{GEO_SCHEMA}.places.tenant_id", f"{GEO_SCHEMA}.places.id"],
            name="fk_place_rel_tenant_place", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "related_place_id"],
            [f"{GEO_SCHEMA}.places.tenant_id", f"{GEO_SCHEMA}.places.id"],
            name="fk_place_rel_tenant_related", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "place_id", "related_place_id", "relationship_type",
                         "transport_mode", name="uq_place_relationships_pair"),
        CheckConstraint("place_id <> related_place_id", name="chk_place_rel_no_self"),
        CheckConstraint(f"relationship_type IN ({values(PlaceRelationshipType)})",
                        name="chk_place_rel_type"),
        CheckConstraint(f"transport_mode IN ({values(TransportMode)})", name="chk_place_rel_transport"),
        CheckConstraint("bearing_deg IS NULL OR (bearing_deg >= 0 AND bearing_deg < 360)",
                        name="chk_place_rel_bearing"),
        CheckConstraint("distance_m IS NULL OR distance_m >= 0", name="chk_place_rel_distance"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_place_rel_status"),
        Index("ix_place_rel_from", "tenant_id", "place_id", "relationship_type",
              postgresql_where=text("status = 'active' AND deleted_at IS NULL")),
        Index("ix_place_rel_to", "related_place_id", postgresql_where=text("deleted_at IS NULL")),
        {"schema": GEO_SCHEMA, "comment": "Place ↔ place relations with per-mode routing metrics."},
    )

    place_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Source place")
    related_place_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Target place")
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_bidirectional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Metrics apply both ways (replaces a free-text 'direction' column)",
    )
    transport_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TransportMode.DRIVING.value, server_default=text("'driving'"),
        comment="Distance and duration differ per mode, so the mode is part of the key",
    )
    sequence_number: Mapped[int | None] = mapped_column(Integer, comment="Order within a named route")
    path: Mapped[object | None] = mapped_column(
        Geography(geometry_type="LINESTRING", srid=4326, spatial_index=True), comment="Route geometry",
    )
    distance_m: Mapped[float | None] = mapped_column(Double, comment="Computed at write time")
    duration_s: Mapped[float | None] = mapped_column(Double)
    bearing_deg: Mapped[float | None] = mapped_column(Double)
    routing_metadata: Mapped[dict | None] = mapped_column(
        JSONB, comment="Directions extract: polyline, warnings, tolls",
    )
    geocode_call_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{GEO_SCHEMA}.geocode_api_calls.id", ondelete="SET NULL",
                   name="fk_place_rel_geocode_call", use_alter=True),
    )
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            f"<PlaceRelationship id={self.id} {self.place_id}→{self.related_place_id} "
            f"{self.relationship_type}/{self.transport_mode}>"
        )
