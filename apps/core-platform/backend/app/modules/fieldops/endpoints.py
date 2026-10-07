"""Route endpoints — "where work starts and ends", one value type for every object that plans work
(docs/fieldops/shift-templates.md §2).

Per side (``start`` / ``end``):

=================  ========================================================  ===============
mode               meaning                                                    geofence
=================  ========================================================  ===============
``anywhere``       no expectation (DEFAULT)                                   —
``hub``            a specific hub; its place (and active fence) is the target  optional
``assigned_hub``   the user's hub for that day (``hubs.user_hub_assignments``) optional
``place``          a particular location (``geo.places``)                      optional
=================  ========================================================  ===============

``enforcement`` NULL = record the check only (advisory); ``advisory`` / ``soft_block`` / ``hard_block``
as for visits. ``radius_m`` NULL = the target's active fence, else the policy's default radius.

Resolution when a shift materializes — the first spec per side that is not ``anywhere`` wins, so a
journey plan can pin the start while the end falls back to the beat::

    explicit on the shift  >  journey plan (future)  >  beat (future)  >  shift template  >  anywhere

The RESOLVED endpoint is frozen onto the shift: ``assigned_hub`` becomes ``hub`` (or ``anywhere`` with
anomaly ``no_hub_assigned`` when the user has no hub that day), and ``place_id`` is the place actually
used. Moving a hub or editing a template never rewrites a past shift.

:class:`RouteEndpointsMixin` gives a table the ten columns; :func:`endpoint_table_args` its FKs and
CHECKs (call it in ``__table_args__`` — mixins cannot contribute constraints that name the table).
"""

from __future__ import annotations

import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.fieldops.enums import EndpointMode, Enforcement, values

SIDES = ("start", "end")


class RouteEndpointsMixin:
    start_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=EndpointMode.ANYWHERE.value,
                                            server_default=text("'anywhere'"),
                                            comment="anywhere | hub | assigned_hub | place")
    start_hub_id: Mapped[int | None] = mapped_column(Integer, comment="hubs.id (mode hub)")
    start_place_id: Mapped[int | None] = mapped_column(BigInteger, comment="geo.places.id (mode place; resolved place for hub)")
    start_enforcement: Mapped[str | None] = mapped_column(String(20), comment="NULL = record only")
    start_radius_m: Mapped[int | None] = mapped_column(Integer, comment="NULL = the fence, else the policy radius")
    end_mode: Mapped[str] = mapped_column(String(16), nullable=False, default=EndpointMode.ANYWHERE.value,
                                          server_default=text("'anywhere'"))
    end_hub_id: Mapped[int | None] = mapped_column(Integer)
    end_place_id: Mapped[int | None] = mapped_column(BigInteger)
    end_enforcement: Mapped[str | None] = mapped_column(String(20))
    end_radius_m: Mapped[int | None] = mapped_column(Integer)


def endpoint_table_args(table: str) -> list:
    out: list = []
    for side in SIDES:
        out += [
            ForeignKeyConstraint(["tenant_id", f"{side}_place_id"], ["geo.places.tenant_id", "geo.places.id"],
                                 name=f"fk_{table}_{side}_place", ondelete="RESTRICT"),
            ForeignKeyConstraint(["tenant_id", f"{side}_hub_id"], ["hubs.tenant_id", "hubs.id"],
                                 name=f"fk_{table}_{side}_hub", ondelete="RESTRICT"),
            CheckConstraint(f"{side}_mode IN ({values(EndpointMode)})", name=f"chk_{table}_{side}_mode"),
            CheckConstraint(f"{side}_enforcement IS NULL OR {side}_enforcement IN ({values(Enforcement)})",
                            name=f"chk_{table}_{side}_enforcement"),
            CheckConstraint(f"{side}_radius_m IS NULL OR {side}_radius_m > 0", name=f"chk_{table}_{side}_radius"),
            CheckConstraint(f"{side}_mode <> 'hub' OR {side}_hub_id IS NOT NULL", name=f"chk_{table}_{side}_hub"),
            CheckConstraint(f"{side}_mode <> 'place' OR {side}_place_id IS NOT NULL",
                            name=f"chk_{table}_{side}_place"),
            CheckConstraint(f"{side}_mode <> 'anywhere' OR ({side}_hub_id IS NULL AND {side}_place_id IS NULL "
                            f"AND {side}_enforcement IS NULL AND {side}_radius_m IS NULL)",
                            name=f"chk_{table}_{side}_anywhere"),
        ]
    return out


# ── the API shape ───────────────────────────────────────────────────────────────

class EndpointIn(BaseModel):
    """Where work starts or ends. ``place`` takes ``place_uuid`` OR ``latitude``/``longitude`` (+ ``address``):
    raw coordinates are found-or-created in ``geo.places`` (geohash near-duplicate probe) — coordinates
    are stored once, there."""

    model_config = ConfigDict(extra="forbid")

    mode: EndpointMode = EndpointMode.ANYWHERE
    hub_id: int | None = Field(None, gt=0)
    place_uuid: uuid_lib.UUID | None = None
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    address: str | None = Field(None, max_length=500)
    name: str | None = Field(None, max_length=255, description="Label for a new place")
    enforcement: Enforcement | None = None
    radius_m: int | None = Field(None, gt=0, le=5000)

    @model_validator(mode="after")
    def _consistent(self) -> EndpointIn:
        mode = self.mode
        if mode is EndpointMode.HUB and self.hub_id is None:
            raise ValueError("mode 'hub' needs hub_id")
        if mode is EndpointMode.PLACE and self.place_uuid is None and (self.latitude is None or self.longitude is None):
            raise ValueError("mode 'place' needs place_uuid, or latitude and longitude")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude go together")
        if mode is not EndpointMode.HUB and self.hub_id is not None:
            raise ValueError("hub_id is only for mode 'hub'")
        if mode is not EndpointMode.PLACE and (self.place_uuid or self.latitude is not None):
            raise ValueError("a place is only for mode 'place'")
        if mode is EndpointMode.ANYWHERE and (self.enforcement is not None or self.radius_m is not None):
            raise ValueError("'anywhere' has no geofence (no enforcement, no radius)")
        return self


class EndpointOut(BaseModel):
    """A resolved endpoint as the app shows it: mode, the target's name/address/coordinates, and its fence."""

    mode: str
    hub_id: int | None = None
    hub_code: str | None = None
    place_uuid: uuid_lib.UUID | None = None
    name: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_m: float | None = None
    geofence_uuid: uuid_lib.UUID | None = None
    geofence_enforcement: str | None = None


@dataclass(slots=True)
class EndpointValue:
    """One side as stored (columns), used by resolution."""

    mode: str = EndpointMode.ANYWHERE.value
    hub_id: int | None = None
    place_id: int | None = None
    enforcement: str | None = None
    radius_m: int | None = None

    @property
    def is_anywhere(self) -> bool:
        return self.mode == EndpointMode.ANYWHERE.value

    @classmethod
    def of(cls, row: Any, side: str) -> EndpointValue:
        return cls(getattr(row, f"{side}_mode") or EndpointMode.ANYWHERE.value, getattr(row, f"{side}_hub_id"),
                   getattr(row, f"{side}_place_id"), getattr(row, f"{side}_enforcement"),
                   getattr(row, f"{side}_radius_m"))

    def apply(self, row: Any, side: str) -> None:
        for name in ("mode", "hub_id", "place_id", "enforcement", "radius_m"):
            setattr(row, f"{side}_{name}", getattr(self, name))

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "hub_id": self.hub_id, "place_id": self.place_id,
                "enforcement": self.enforcement, "radius_m": self.radius_m}


async def from_input(db: AsyncSession, spec: EndpointIn | None, *, tenant_id: int, organization_id: int) -> EndpointValue:
    """API input → stored value. Validates the hub / place exists in the tenant; raw coordinates become
    a place (found or created)."""
    from app.modules.fieldops.errors import FieldOpsRuleError

    if spec is None or spec.mode is EndpointMode.ANYWHERE:
        return EndpointValue()
    enforcement = spec.enforcement.value if spec.enforcement else None
    if spec.mode is EndpointMode.HUB:
        hub = (await db.execute(text("SELECT id, place_id FROM hubs WHERE id = :id AND tenant_id = :t "
                                     "AND deleted_at IS NULL"), {"id": spec.hub_id, "t": tenant_id})).first()
        if hub is None:
            raise FieldOpsRuleError("hub_not_found", f"Hub {spec.hub_id} not found", data={"hub_id": spec.hub_id})
        return EndpointValue(EndpointMode.HUB.value, hub.id, hub.place_id, enforcement, spec.radius_m)
    if spec.mode is EndpointMode.ASSIGNED_HUB:
        return EndpointValue(EndpointMode.ASSIGNED_HUB.value, None, None, enforcement, spec.radius_m)
    if spec.place_uuid is not None:
        place_id = await db.scalar(text("SELECT id FROM geo.places WHERE uuid = :u AND tenant_id = :t "
                                        "AND deleted_at IS NULL"), {"u": spec.place_uuid, "t": tenant_id})
        if place_id is None:
            raise FieldOpsRuleError("place_not_found", f"Place {spec.place_uuid} not found")
    else:
        place_id = await find_or_create_place(db, latitude=spec.latitude, longitude=spec.longitude,
                                              address=spec.address, name=spec.name, tenant_id=tenant_id,
                                              organization_id=organization_id)
    return EndpointValue(EndpointMode.PLACE.value, None, int(place_id), enforcement, spec.radius_m)


async def find_or_create_place(db: AsyncSession, *, latitude: float, longitude: float, address: str | None,
                               name: str | None, tenant_id: int, organization_id: int) -> int:
    """A manager-given coordinate as a ``geo.places`` row: reuse a live place in the same ~19 m geohash
    cell (the geo module's near-duplicate probe), else create a ``manual``-verified address place.
    ``field_verified`` because a manager pinned it on purpose — the verifier then trusts its radius."""
    from geoalchemy2 import WKTElement

    from app.modules.geo.model import Place

    existing = await db.scalar(text("""
        SELECT id FROM geo.places
         WHERE tenant_id = :t AND deleted_at IS NULL
           AND geohash8 = ST_GeoHash(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 8)
         ORDER BY (verification_status = 'field_verified') DESC, id LIMIT 1
    """), {"t": tenant_id, "lat": latitude, "lng": longitude})
    if existing is not None:
        return int(existing)
    place = Place(kind="address", location_name=(name or address or "Shift location")[:255],
                  formatted_address=address, coordinates=WKTElement(f"POINT({longitude} {latitude})", srid=4326),
                  verification_status="field_verified", is_verified=True, organization_id=organization_id)
    db.add(place)
    await db.flush()
    return place.id


__all__ = [
    "SIDES", "EndpointIn", "EndpointOut", "EndpointValue", "RouteEndpointsMixin", "endpoint_table_args",
    "find_or_create_place", "from_input",
]
