"""Reference layer — the shapes everything else is measured against.

``AdminBoundary``  one row per administrative area (country → state →
                  district → taluka → city → locality → pincode, plus the
                  electoral levels). ONE copy of each boundary polygon for the
                  whole platform.
``Geofence``      a real polygon (or centre + radius) with a behaviour policy,
                  owned by a tenant's organization.

Why AdminBoundary is GLOBAL (no ``tenant_id``)
----------------------------------------------
Maharashtra's boundary is not one tenant's data, and a MULTIPOLYGON of a
district is measured in megabytes — copying it per tenant would multiply the
largest rows in the database for no gain. It joins ``countries`` and
``timezones`` in the allow-list of explained global tables
(tests/test_tenancy.py). Anything a tenant draws for itself — beats,
territories, hub zones — is a ``Geofence``, which *is* tenant-scoped.
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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDMixin,
    DeactivationMixin,
    OrgEntityMixin,
    RowVersionMixin,
    StatusMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.geo.enums import AdminLevel, FenceType, values

GEO_SCHEMA = "geo"


class AdminBoundary(
    BigIntPKWithUUIDMixin, AuditMixin, StatusMixin, RowVersionMixin, AppMetaMixin,
    TimestampMixin, SoftDeleteFilteredMixin, Base,
):
    """An administrative area with authoritative geometry and official codes."""

    __tablename__ = "admin_boundaries"
    __table_args__ = (
        UniqueConstraint("level", "path", name="uq_admin_boundaries_level_path"),
        CheckConstraint(f"level IN ({values(AdminLevel)})", name="chk_admin_boundary_level"),
        CheckConstraint("path LIKE '/%' AND path LIKE '%/'", name="chk_admin_boundary_path"),
        ForeignKeyConstraint(["parent_id"], [f"{GEO_SCHEMA}.admin_boundaries.id"],
                             name="fk_admin_boundaries_parent", ondelete="SET NULL"),
        Index("ix_admin_boundaries_parent", "parent_id"),
        # Subtree scans: WHERE path LIKE '/india/maharashtra/%'
        Index("ix_admin_boundaries_path", "path", postgresql_ops={"path": "text_pattern_ops"}),
        Index("ix_admin_boundaries_lgd_code", "lgd_code", postgresql_where=text("lgd_code IS NOT NULL")),
        Index("ix_admin_boundaries_pincode", "pincode", postgresql_where=text("pincode IS NOT NULL")),
        # Address forms type ahead: "puné", "Pune", "पुणे"
        Index("ix_admin_boundaries_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "gin_trgm_ops"}),
        {"schema": GEO_SCHEMA,
         "comment": "Administrative areas (global reference data — see the module docstring)."},
    )

    level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Canonical English name")
    name_local: Mapped[str | None] = mapped_column(String(255), comment="Vernacular name (e.g. पुणे)")
    alt_names: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), comment="Alternative spellings — fuzzy address matching",
    )
    #: Materialized path of slugs INCLUDING self: ``/india/maharashtra/pune/``.
    #: Same shape as org_management.organizations.hierarchy_path — one tree
    #: idiom in the codebase rather than an ltree here and a text path there.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    parent_id: Mapped[int | None] = mapped_column(BigInteger)

    # ---- Official codes (India-first; ISO for the rest) ---------------------
    lgd_code: Mapped[str | None] = mapped_column(String(32), comment="Local Government Directory code")
    census_code: Mapped[str | None] = mapped_column(String(32), comment="Census of India code")
    state_code: Mapped[str | None] = mapped_column(String(10), comment="MH / KA / DL …")
    geoname_id: Mapped[str | None] = mapped_column(String(32))
    iso_code: Mapped[str | None] = mapped_column(String(16), comment="ISO 3166 code, where one exists")
    pincode: Mapped[str | None] = mapped_column(String(16), comment="Set when level = 'pincode'")

    centroid: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        comment="Representative point — cheap enough to read on every address form",
    )
    boundary: Mapped[object | None] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True),
        comment="Authoritative polygon; ONE copy platform-wide",
    )
    timezone: Mapped[str | None] = mapped_column(String(64), comment="IANA timezone of the area")
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Population, data source, vintage …",
    )

    parent: Mapped[AdminBoundary | None] = relationship(remote_side="AdminBoundary.id", viewonly=True)

    @property
    def path_slugs(self) -> list[str]:
        return [part for part in (self.path or "").split("/") if part]

    def __repr__(self) -> str:
        return f"<AdminBoundary id={self.id} {self.level}:{self.name!r}>"


class Geofence(BigIntPKWithUUIDMixin, OrgEntityMixin, DeactivationMixin, SoftDeleteFilteredMixin, Base):
    """A polygon or circle with a behaviour policy, owned by an organization.

    ``dwell_threshold_s`` exists because a fence without one is a pager: a
    phone's position bounces across a boundary for a second and fires an
    entry event that never happened. Nothing may fire before a fix has stayed
    inside for this long.
    """

    __tablename__ = "geofences"
    __table_args__ = (
        CheckConstraint("boundary IS NOT NULL OR (center IS NOT NULL AND radius_m IS NOT NULL)",
                        name="chk_geofence_shape_present"),
        CheckConstraint("radius_m IS NULL OR radius_m > 0", name="chk_geofence_radius_positive"),
        CheckConstraint("dwell_threshold_s >= 0", name="chk_geofence_dwell_nonnegative"),
        CheckConstraint(f"fence_type IN ({values(FenceType)})", name="chk_geofence_type"),
        CheckConstraint("status IN ('active','suspended','archived')", name="chk_geofence_status"),
        CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                        name="chk_geofence_validity"),
        Index("uq_geofences_name_live", "tenant_id", "organization_id", "name", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_geofences_place", "place_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_geofences_evaluated", "tenant_id", "fence_type",
              postgresql_where=text("status = 'active' AND deleted_at IS NULL")),
        {"schema": GEO_SCHEMA, "comment": "Tenant-drawn zones with an entry/exit/dwell policy."},
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    fence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    place_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{GEO_SCHEMA}.places.id", ondelete="CASCADE", name="fk_geofences_place"),
        comment="The place this fence guards (fence_type = place_radius)",
    )
    boundary: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=True),
        comment="Polygon fence (preferred)",
    )
    center: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True), comment="Circle-fence centre",
    )
    radius_m: Mapped[float | None] = mapped_column(Double, comment="Circle-fence radius in metres")

    dwell_threshold_s: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60"),
        comment="Seconds a fix must stay inside before anything fires (jitter guard)",
    )
    speed_limit_kmh: Mapped[float | None] = mapped_column(Double, comment="Max speed inside the zone")
    entry_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    exit_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), comment="['high_risk','warehouse']")
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return f"<Geofence id={self.id} name={self.name!r} type={self.fence_type!r}>"
