"""``hubs`` — the operational hub/branch master.

    hubs   ENTITY   an operating point (warehouse/branch/dark store/…) owned by
                    an organization, pointing at its geo place + geofence

Scoping: ``OrgEntityMixin`` (``organization_id`` NOT NULL) + soft delete.
The address and the zone are NOT stored here — ``place_id`` → ``geo.places``
and ``geofence_id`` → ``geo.geofences`` keep the canonical location in one
place for the whole platform. ``parent_hub_id`` is a tenant-safe self-FK so the
hub tree (warehouse → spoke) survives.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    DeactivationMixin,
    IntPKMixin,
    OrgEntityMixin,
    VerificationMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.documents.mixins import HasDocumentsMixin
from app.modules.hubs.enums import HubStatus, HubType, values

_STATUS_SQL = values(HubStatus)


class Hub(
    IntPKMixin, OrgEntityMixin, VerificationMixin, DeactivationMixin,
    SoftDeleteFilteredMixin, HasDocumentsMixin, Base,
):
    """An operating point of an organization — warehouse, branch, dark store …"""

    __tablename__ = "hubs"
    __table_args__ = (
        # Target of children's composite FKs and of the self-FK below.
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_hubs_tenant_org_id"),
        UniqueConstraint("tenant_id", "id", name="uq_hubs_tenant_id"),
        # The hub tree: a parent and child always share a tenant.
        ForeignKeyConstraint(
            ["tenant_id", "parent_hub_id"],
            ["hubs.tenant_id", "hubs.id"],
            name="fk_hubs_parent", ondelete="RESTRICT",
        ),
        CheckConstraint(f"hub_type IN ({values(HubType)})", name="chk_hubs_type"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="chk_hubs_status"),
        CheckConstraint("parent_hub_id IS NULL OR parent_hub_id <> id", name="chk_hubs_not_own_parent"),
        CheckConstraint("storage_capacity_sqft IS NULL OR storage_capacity_sqft >= 0",
                        name="chk_hubs_capacity"),
        CheckConstraint("dock_count IS NULL OR dock_count >= 0", name="chk_hubs_dock_count"),
        CheckConstraint("vehicle_capacity IS NULL OR vehicle_capacity >= 0", name="chk_hubs_vehicle_capacity"),
        # Stable code, unique per organization among live rows.
        Index("uq_hubs_tenant_org_code_live", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        # A Zoho location maps to at most one live hub per tenant.
        Index("uq_hubs_zoho_location_live", "tenant_id", "zoho_location_id", unique=True,
              postgresql_where=text("deleted_at IS NULL AND zoho_location_id IS NOT NULL")),
        Index("ix_hubs_parent", "tenant_id", "parent_hub_id",
              postgresql_where=text("parent_hub_id IS NOT NULL")),
        Index("ix_hubs_place", "place_id", postgresql_where=text("place_id IS NOT NULL")),
        Index("ix_hubs_geofence", "geofence_id", postgresql_where=text("geofence_id IS NOT NULL")),
        Index("ix_hubs_manager", "tenant_id", "manager_user_id",
              postgresql_where=text("manager_user_id IS NOT NULL")),
        Index("ix_hubs_type_status", "tenant_id", "organization_id", "hub_type", "status",
              postgresql_where=text("deleted_at IS NULL")),
        {"comment": "Operational hubs/branches; the address and zone live in geo."},
    )

    # ---- Identity ----------------------------------------------------------
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Stable short code, e.g. HUB-AHM-01")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Display name, e.g. 'North Ahmedabad Hub'")
    hub_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=HubType.WAREHOUSE.value, server_default=text("'warehouse'"),
        comment="warehouse / branch / dark_store / transit / spoke",
    )
    parent_hub_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Containing hub (warehouse → spoke); NULL = top-level",
    )

    # ---- Location (canonical data lives in geo) ----------------------------
    place_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.places.id", ondelete="SET NULL"),
        comment="The hub's address/coordinates (geo.places)",
    )
    geofence_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("geo.geofences.id", ondelete="SET NULL"),
        comment="The hub zone fence (geo.geofences)",
    )
    timezone: Mapped[str | None] = mapped_column(String(64), comment="IANA timezone at the hub")

    # ---- Operations --------------------------------------------------------
    manager_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), comment="Hub manager (users.id)",
    )
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    operating_hours: Mapped[dict | None] = mapped_column(
        JSONB, comment='{"mon": [["09:00","18:00"]], …} — structured, not free text',
    )
    daily_cutoff_time: Mapped[dt.time | None] = mapped_column(
        Time, comment="Latest time an order can be assigned to today's run",
    )
    storage_capacity_sqft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dock_count: Mapped[int | None] = mapped_column(Integer, comment="Loading/unloading bays")
    vehicle_capacity: Mapped[int | None] = mapped_column(Integer, comment="Vehicles that can be staged")
    serviceable_pincodes: Mapped[list | None] = mapped_column(
        ARRAY(String), comment="PIN codes this hub serves (NULL = not restricted)",
    )

    # ---- External systems --------------------------------------------------
    zoho_location_id: Mapped[str | None] = mapped_column(
        String(50), comment="Zoho location id whose geo.places row this hub operates at",
    )

    # ---- Extras ------------------------------------------------------------
    notes: Mapped[str | None] = mapped_column(String(1000))
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Business extras (dock height, gate code). App-level data goes in app_metadata",
    )

    @property
    def is_zoho_linked(self) -> bool:
        return self.zoho_location_id is not None

    def __repr__(self) -> str:
        return f"<Hub id={self.id} code={self.code!r} type={self.hub_type!r} status={self.status!r}>"
