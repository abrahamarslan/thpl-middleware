"""Location hub business logic.

| Rule | Enforced by |
|---|---|
| a row always belongs to one organization of the caller's tenant | ``MultiTenantMixin`` (DB) + ``require_organization`` |
| a place's coordinates never disagree with its decimals | GENERATED columns — the app cannot write them |
| the same doorway is not stored twice | ``geohash8`` probe + the provider-place unique index |
| one primary address per owner and link type | partial unique index |
| ``current`` / ``permanent`` addresses never overlap in time | EXCLUDE constraint (btree_gist) |
| a document's address never changes under it | ``snapshot`` frozen at link time |
| a place in use is archived, never deleted | ``archive_place`` counts its live links |
| Zoho-owned fields are read-only on a Zoho-linked place | ``ZOHO_OWNED_PLACE_FIELDS`` |
| concurrent edits don't overwrite each other | ``row_version`` |
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

import structlog
from geoalchemy2 import WKTElement
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.activity.recorder import record_activity
from app.modules.geo.enums import SINGLE_VALUED_LINKS, LinkType, PlaceKind, PlaceStatus
from app.modules.geo.model import (
    AdminBoundary,
    Geofence,
    Place,
    PlaceLink,
    PlaceRelationship,
    ZOHO_OWNED_PLACE_FIELDS,
)
from app.modules.geo.scope import GeoRuleError, require_organization
from app.modules.geo.schema import (
    AddressCreate,
    AddressUpdate,
    AdminBoundaryCreate,
    Coordinates,
    GeofenceCreate,
    GeofenceUpdate,
    PlaceCreate,
    PlaceUpdate,
    PlaceVerify,
)

logger = structlog.get_logger("app.geo")

#: Distance under which two places are treated as the same doorway.
DUPLICATE_RADIUS_M = 25.0

#: Postal fields copied into a frozen snapshot.
SNAPSHOT_FIELDS = (
    "location_name", "attention", "formatted_address", "building_name", "street", "street2",
    "landmark", "sub_locality", "locality", "city", "district", "taluka", "state", "state_code",
    "postal_code", "country", "country_code", "phone", "contact_person_name", "contact_email",
)


def _point(latitude: float | None, longitude: float | None) -> WKTElement | None:
    """WGS84 point. Longitude first — the order every geo API uses and every
    hand-written call gets backwards at least once."""
    if latitude is None or longitude is None:
        return None
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def _check_version(row: Any, seen: int, label: str) -> None:
    if row.row_version != seen:
        raise ConflictError(
            f"{label} changed since you loaded it (version {seen} → {row.row_version}); reload and retry",
            data={"current_row_version": row.row_version},
        )


def _by_ref(model: Any, ref: str):
    """uuid (preferred) or numeric id."""
    try:
        return model.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        if str(ref).isdigit():
            return model.id == int(ref)
        raise NotFoundError(f"'{ref}' is not a valid reference") from None


# ── places ──────────────────────────────────────────────────────────────────

async def get_place(db: AsyncSession, ref: str | uuid_lib.UUID) -> Place:
    place = await db.scalar(select(Place).where(_by_ref(Place, str(ref))).limit(1))
    if place is None:
        raise NotFoundError(f"Place '{ref}' not found")
    return place


async def list_places(
    db: AsyncSession, *, kind: str | None = None, status: str | None = None, q: str | None = None,
    postal_code: str | None = None, verified: bool | None = None, parent: uuid_lib.UUID | None = None,
    page: int = 1, page_size: int = 50,
) -> list[Place]:
    stmt = select(Place).order_by(Place.location_name.nulls_last(), Place.id)
    if kind:
        stmt = stmt.where(Place.kind == kind)
    if status:
        stmt = stmt.where(Place.status == status)
    if postal_code:
        stmt = stmt.where(Place.postal_code == postal_code)
    if verified is not None:
        stmt = stmt.where(Place.is_verified.is_(verified))
    if parent is not None:
        parent_place = await get_place(db, parent)
        stmt = stmt.where(Place.parent_location_id == parent_place.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Place.location_name.ilike(like), Place.formatted_address.ilike(like),
            Place.street.ilike(like), Place.city.ilike(like), Place.landmark.ilike(like),
        ))
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


async def nearby_places(
    db: AsyncSession, *, latitude: float, longitude: float, radius_m: float = 1000,
    kind: str | None = None, limit: int = 25,
) -> list[Place]:
    """Places within a radius, nearest first — served by the GiST index on
    ``coordinates``. ``ST_DWithin`` on geography measures real metres."""
    point = _point(latitude, longitude)
    stmt = (
        select(Place)
        .where(Place.coordinates.isnot(None), func.ST_DWithin(Place.coordinates, point, radius_m))
        .order_by(func.ST_Distance(Place.coordinates, point))
        .limit(limit)
    )
    if kind:
        stmt = stmt.where(Place.kind == kind)
    return list((await db.scalars(stmt)).all())


async def find_duplicate(
    db: AsyncSession, *, latitude: float | None, longitude: float | None, postal_code: str | None = None,
    street: str | None = None,
) -> Place | None:
    """The near-duplicate probe run before writing a new place.

    Coordinates first (a doorway is a doorway whatever the spelling), then a
    postal-code + street fallback for addresses that were never geocoded.
    """
    if latitude is not None and longitude is not None:
        point = _point(latitude, longitude)
        return await db.scalar(
            select(Place)
            .where(Place.coordinates.isnot(None), func.ST_DWithin(Place.coordinates, point, DUPLICATE_RADIUS_M))
            .order_by(func.ST_Distance(Place.coordinates, point))
            .limit(1)
        )
    if postal_code and street:
        return await db.scalar(
            select(Place)
            .where(Place.postal_code == postal_code, func.lower(Place.street) == street.lower().strip())
            .limit(1)
        )
    return None


async def _resolve_parent_place(db: AsyncSession, ref: uuid_lib.UUID | None) -> Place | None:
    if ref is None:
        return None
    parent = await get_place(db, ref)
    if parent.status == PlaceStatus.ARCHIVED.value:
        raise GeoRuleError(f"Parent place '{parent.location_name or parent.uuid}' is archived")
    return parent


async def _clear_other_primaries(db: AsyncSession, place: Place) -> None:
    """One primary per organization and kind — clear the old one rather than
    letting the partial unique index reject the write."""
    stmt = select(Place).where(
        Place.organization_id == place.organization_id, Place.kind == place.kind,
        Place.is_primary.is_(True),
    )
    if place.id is not None:
        stmt = stmt.where(Place.id != place.id)
    for other in (await db.scalars(stmt)).all():
        other.is_primary = False


async def create_place(
    db: AsyncSession, body: PlaceCreate, *, actor_id: int | None = None, reuse_duplicates: bool = True,
) -> Place:
    organization_id = await require_organization(db)
    parent = await _resolve_parent_place(db, body.parent_location)

    if reuse_duplicates:
        existing = await find_duplicate(
            db, latitude=body.latitude, longitude=body.longitude,
            postal_code=body.postal_code, street=body.street,
        )
        if existing is not None:
            logger.info("geo.place.reused", place_id=existing.id, reason="near_duplicate")
            return existing

    values = body.model_dump(exclude={"parent_location", "latitude", "longitude"}, exclude_none=True)
    values["kind"] = body.kind.value
    place = Place(**values, organization_id=organization_id)
    place.coordinates = _point(body.latitude, body.longitude)
    if parent is not None:
        place.parent_location_id = parent.id
    if not place.formatted_address:
        place.formatted_address = compose_address(place)
    if place.is_primary:
        await _clear_other_primaries(db, place)

    db.add(place)
    await db.flush()
    await record_activity(
        db, action="place_created", actor_id=actor_id, subject_type="Place", subject_id=place.id,
        changes={"after": {"kind": place.kind, "name": place.location_name,
                           "address": place.formatted_address}},
    )
    return place


async def update_place(
    db: AsyncSession, ref: str, body: PlaceUpdate, *, actor_id: int | None = None,
) -> Place:
    place = await get_place(db, ref)
    _check_version(place, body.row_version, f"Place '{place.location_name or place.uuid}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "parent_location"})

    if place.is_zoho_linked:
        blocked = sorted(set(changes) & ZOHO_OWNED_PLACE_FIELDS)
        if blocked:
            raise GeoRuleError(
                f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for this "
                f"place (location {place.zoho_id}); change it in Zoho — the next sync brings it here.",
                data={"zoho_owned": blocked},
            )

    latitude, longitude = changes.pop("latitude", None), changes.pop("longitude", None)
    if latitude is not None and longitude is not None:
        place.coordinates = _point(latitude, longitude)
        # The coordinates moved: whatever verified the old point no longer
        # vouches for this one.
        place.mark_unverified()
    if "parent_location" in body.model_fields_set:
        parent = await _resolve_parent_place(db, body.parent_location)
        if parent is not None and parent.id == place.id:
            raise GeoRuleError("A place cannot contain itself")
        place.parent_location_id = parent.id if parent else None

    for field in ("kind", "status"):
        if field in changes and changes[field] is not None:
            changes[field] = getattr(changes[field], "value", changes[field])

    before = {k: getattr(place, k, None) for k in changes}
    for field, value in changes.items():
        setattr(place, field, value)
    if changes.get("is_primary"):
        await _clear_other_primaries(db, place)
    if any(field in changes for field in SNAPSHOT_FIELDS) and "formatted_address" not in changes:
        place.formatted_address = compose_address(place)

    await db.flush()
    await record_activity(
        db, action="place_updated", actor_id=actor_id, subject_type="Place", subject_id=place.id,
        changes={"before": {k: _jsonable(v) for k, v in before.items()},
                 "after": {k: _jsonable(v) for k, v in changes.items()}},
    )
    return place


async def verify_place(db: AsyncSession, ref: str, body: PlaceVerify, *, actor_id: int | None = None) -> Place:
    place = await get_place(db, ref)
    place.mark_verified(
        method=body.verification_method, status=body.verification_status.value,
        data=body.verification_data, by=actor_id,
    )
    await db.flush()
    await record_activity(
        db, action="place_verified", actor_id=actor_id, subject_type="Place", subject_id=place.id,
        context={"method": body.verification_method, "status": body.verification_status.value},
    )
    return place


async def live_link_count(db: AsyncSession, place: Place) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(PlaceLink).where(PlaceLink.place_id == place.id)
    ) or 0)


async def archive_place(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> Place:
    """Archive rather than delete: an address referenced by a paid invoice
    must stay readable for as long as the invoice does."""
    place = await get_place(db, ref)
    children = await db.scalar(
        select(func.count()).select_from(Place).where(Place.parent_location_id == place.id)
    )
    if children:
        raise GeoRuleError(f"'{place.location_name or place.uuid}' still contains {children} place(s)")
    place.status = PlaceStatus.ARCHIVED.value
    place.is_primary = False
    place.deactivate(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="place_archived", actor_id=actor_id, subject_type="Place", subject_id=place.id,
        context={"reason": reason},
    )
    return place


async def delete_place(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    place = await get_place(db, ref)
    if place.is_zoho_linked:
        raise GeoRuleError(
            f"This place mirrors Zoho location {place.zoho_id}; archive it instead — the next sync "
            "would recreate it."
        )
    in_use = await live_link_count(db, place)
    if in_use:
        raise GeoRuleError(
            f"{in_use} address(es) still point at this place; detach them or archive the place instead.",
            data={"links": in_use},
        )
    place.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="place_deleted", actor_id=actor_id, subject_type="Place", subject_id=place.id,
        context={"reason": reason},
    )


def compose_address(place: Place) -> str:
    """A readable one-line address from whatever parts exist."""
    parts = [
        place.attention, place.building_name, place.street, place.street2,
        f"near {place.landmark}" if place.landmark else None,
        place.sub_locality, place.locality, place.city, place.district, place.state,
        place.postal_code, place.country,
    ]
    return ", ".join(p.strip() for p in parts if p and p.strip())


# ── addresses (place links) ─────────────────────────────────────────────────

async def get_address(db: AsyncSession, ref: str | uuid_lib.UUID) -> PlaceLink:
    link = await db.scalar(
        select(PlaceLink).where(_by_ref(PlaceLink, str(ref))).options(selectinload(PlaceLink.place)).limit(1)
    )
    if link is None:
        raise NotFoundError(f"Address '{ref}' not found")
    return link


async def list_addresses(
    db: AsyncSession, *, owner_type: str | None = None, owner_id: int | None = None,
    link_type: str | None = None, place: uuid_lib.UUID | None = None, current_only: bool = True,
    page: int = 1, page_size: int = 50,
) -> list[PlaceLink]:
    stmt = (
        select(PlaceLink)
        .options(selectinload(PlaceLink.place))
        .order_by(PlaceLink.is_primary.desc(), PlaceLink.link_type, PlaceLink.id)
    )
    if owner_type:
        stmt = stmt.where(PlaceLink.owner_type == owner_type)
    if owner_id:
        stmt = stmt.where(PlaceLink.owner_id == owner_id)
    if link_type:
        stmt = stmt.where(PlaceLink.link_type == link_type)
    if place is not None:
        stmt = stmt.where(PlaceLink.place_id == (await get_place(db, place)).id)
    if current_only:
        stmt = stmt.where(PlaceLink.valid_to.is_(None))
    return list((await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all())


def build_snapshot(place: Place) -> dict:
    """The address as printed, frozen. Kept flat and plain so it survives any
    later change to the model."""
    snapshot = {field: getattr(place, field, None) for field in SNAPSHOT_FIELDS}
    snapshot["place_uuid"] = str(place.uuid)
    snapshot["latitude"] = float(place.latitude) if place.latitude is not None else None
    snapshot["longitude"] = float(place.longitude) if place.longitude is not None else None
    snapshot["frozen_at"] = dt.datetime.now(dt.UTC).isoformat()
    return {k: v for k, v in snapshot.items() if v is not None}


async def _close_single_valued(db: AsyncSession, link: PlaceLink) -> None:
    """``current`` / ``permanent`` are one-at-a-time: the arriving address
    closes the one it supersedes, which is also what keeps the history."""
    if LinkType(link.link_type) not in SINGLE_VALUED_LINKS:
        return
    open_rows = (await db.scalars(
        select(PlaceLink).where(
            PlaceLink.owner_type == link.owner_type, PlaceLink.owner_id == link.owner_id,
            PlaceLink.link_type == link.link_type, PlaceLink.valid_to.is_(None),
            PlaceLink.id != (link.id or -1),
        )
    )).all()
    for row in open_rows:
        row.close(at=link.valid_from)


async def _clear_other_primary_links(db: AsyncSession, link: PlaceLink) -> None:
    rows = (await db.scalars(
        select(PlaceLink).where(
            PlaceLink.owner_type == link.owner_type, PlaceLink.owner_id == link.owner_id,
            PlaceLink.link_type == link.link_type, PlaceLink.is_primary.is_(True),
            PlaceLink.valid_to.is_(None), PlaceLink.id != (link.id or -1),
        )
    )).all()
    for row in rows:
        row.is_primary = False


async def attach_address(
    db: AsyncSession, body: AddressCreate, *, actor_id: int | None = None,
) -> PlaceLink:
    organization_id = await require_organization(db)
    place = (
        await get_place(db, body.place) if body.place is not None
        else await create_place(db, body.new_place, actor_id=actor_id)
    )
    if place.status != PlaceStatus.ACTIVE.value:
        raise GeoRuleError(f"Place '{place.location_name or place.uuid}' is {place.status}")

    values = body.model_dump(
        exclude={"place", "new_place", "freeze", "owner_type", "link_type", "valid_from"},
        exclude_none=True,
    )
    link = PlaceLink(
        **values,
        organization_id=organization_id,
        owner_type=body.owner_type,
        link_type=body.link_type.value,
        place_id=place.id,
        valid_from=body.valid_from or dt.datetime.now(dt.UTC),
    )
    if body.freeze:
        link.snapshot = build_snapshot(place)
    await _close_single_valued(db, link)
    if link.is_primary:
        await _clear_other_primary_links(db, link)

    db.add(link)
    await db.flush()
    link = await get_address(db, link.uuid)          # loads .place (lazy="raise")
    await record_activity(
        db, action="address_attached", actor_id=actor_id, subject_type="PlaceLink", subject_id=link.id,
        changes={"after": {"owner": f"{link.owner_type}:{link.owner_id}", "link_type": link.link_type,
                           "place": str(place.uuid), "frozen": link.is_frozen}},
    )
    logger.info("geo.address.attached", link_id=link.id, owner=f"{link.owner_type}:{link.owner_id}",
                place_id=place.id, link_type=link.link_type)
    return link


async def update_address(
    db: AsyncSession, ref: str, body: AddressUpdate, *, actor_id: int | None = None,
) -> PlaceLink:
    link = await get_address(db, ref)
    _check_version(link, body.row_version, "Address")
    if link.is_frozen:
        raise GeoRuleError(
            "This address is a frozen snapshot on a document and cannot be edited; "
            "attach a new address instead.",
        )
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "link_type" in changes and changes["link_type"] is not None:
        changes["link_type"] = changes["link_type"].value

    before = {k: getattr(link, k, None) for k in changes}
    for field, value in changes.items():
        setattr(link, field, value)
    if changes.get("is_primary"):
        await _clear_other_primary_links(db, link)
    await db.flush()
    await record_activity(
        db, action="address_updated", actor_id=actor_id, subject_type="PlaceLink", subject_id=link.id,
        changes={"before": {k: _jsonable(v) for k, v in before.items()},
                 "after": {k: _jsonable(v) for k, v in changes.items()}},
    )
    return link


async def verify_address(
    db: AsyncSession, ref: str, body: PlaceVerify, *, actor_id: int | None = None,
) -> PlaceLink:
    link = await get_address(db, ref)
    link.mark_verified(
        method=body.verification_method, status=body.verification_status.value,
        data=body.verification_data, by=actor_id,
    )
    await db.flush()
    await record_activity(
        db, action="address_verified", actor_id=actor_id, subject_type="PlaceLink", subject_id=link.id,
        context={"method": body.verification_method},
    )
    return link


async def detach_address(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    """Detaching IS the soft delete — who, when and why, in one place."""
    link = await get_address(db, ref)
    if link.is_frozen:
        raise GeoRuleError("A frozen document address cannot be detached; it is part of the record.")
    link.close()
    link.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="address_detached", actor_id=actor_id, subject_type="PlaceLink", subject_id=link.id,
        context={"reason": reason},
    )


async def address_history(
    db: AsyncSession, *, owner_type: str, owner_id: int, link_type: str | None = None,
) -> list[PlaceLink]:
    """Every address an owner has held, newest window first — including the
    closed ones, which is the whole point of effective dating."""
    stmt = (
        select(PlaceLink)
        .options(selectinload(PlaceLink.place))
        .where(PlaceLink.owner_type == owner_type, PlaceLink.owner_id == owner_id)
        .order_by(PlaceLink.valid_from.desc())
        .execution_options(include_deleted=True)
    )
    if link_type:
        stmt = stmt.where(PlaceLink.link_type == link_type)
    return list((await db.scalars(stmt)).all())


# ── geofences ───────────────────────────────────────────────────────────────

def _polygon(ring: list[Coordinates]) -> WKTElement:
    points = list(ring)
    if (points[0].latitude, points[0].longitude) != (points[-1].latitude, points[-1].longitude):
        points.append(points[0])                       # a ring must close
    body = ", ".join(f"{p.longitude} {p.latitude}" for p in points)
    return WKTElement(f"POLYGON(({body}))", srid=4326)


async def get_geofence(db: AsyncSession, ref: str | uuid_lib.UUID) -> Geofence:
    fence = await db.scalar(select(Geofence).where(_by_ref(Geofence, str(ref))).limit(1))
    if fence is None:
        raise NotFoundError(f"Geofence '{ref}' not found")
    return fence


async def list_geofences(
    db: AsyncSession, *, fence_type: str | None = None, status: str | None = "active",
) -> list[Geofence]:
    stmt = select(Geofence).order_by(Geofence.name)
    if fence_type:
        stmt = stmt.where(Geofence.fence_type == fence_type)
    if status:
        stmt = stmt.where(Geofence.status == status)
    return list((await db.scalars(stmt)).all())


async def create_geofence(db: AsyncSession, body: GeofenceCreate, *, actor_id: int | None = None) -> Geofence:
    organization_id = await require_organization(db)
    fence = Geofence(
        organization_id=organization_id,
        name=body.name,
        fence_type=body.fence_type.value,
        radius_m=body.radius_m,
        dwell_threshold_s=body.dwell_threshold_s if body.dwell_threshold_s is not None else 60,
        speed_limit_kmh=body.speed_limit_kmh,
        entry_alert=True if body.entry_alert is None else body.entry_alert,
        exit_alert=True if body.exit_alert is None else body.exit_alert,
        tags=body.tags,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        custom_attributes=body.custom_attributes or {},
    )
    if body.place is not None:
        fence.place_id = (await get_place(db, body.place)).id
    if body.polygon:
        fence.boundary = _polygon(body.polygon)
    if body.center:
        fence.center = _point(body.center.latitude, body.center.longitude)
    db.add(fence)
    await db.flush()
    await record_activity(
        db, action="geofence_created", actor_id=actor_id, subject_type="Geofence", subject_id=fence.id,
        changes={"after": {"name": fence.name, "type": fence.fence_type}},
    )
    return fence


async def update_geofence(
    db: AsyncSession, ref: str, body: GeofenceUpdate, *, actor_id: int | None = None,
) -> Geofence:
    fence = await get_geofence(db, ref)
    _check_version(fence, body.row_version, f"Geofence '{fence.name}'")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "place", "polygon", "center"})
    if body.polygon is not None:
        fence.boundary = _polygon(body.polygon)
    if body.center is not None:
        fence.center = _point(body.center.latitude, body.center.longitude)
    if "place" in body.model_fields_set:
        fence.place_id = (await get_place(db, body.place)).id if body.place else None
    for field, value in changes.items():
        setattr(fence, field, getattr(value, "value", value))
    if changes.get("status") in ("suspended", "archived"):
        fence.deactivate(reason="status change", by=actor_id)
    elif changes.get("status") == "active":
        fence.reactivate()
    await db.flush()
    return fence


async def delete_geofence(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    fence = await get_geofence(db, ref)
    fence.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="geofence_deleted", actor_id=actor_id, subject_type="Geofence", subject_id=fence.id,
        context={"reason": reason},
    )


async def fences_containing(db: AsyncSession, *, latitude: float, longitude: float) -> list[Geofence]:
    """Which active fences hold this point — polygon fences by containment,
    circle fences by distance. One query, both shapes."""
    point = _point(latitude, longitude)
    return list((await db.scalars(
        select(Geofence)
        .where(
            Geofence.status == "active",
            or_(
                func.ST_Covers(Geofence.boundary, point),
                func.ST_DWithin(Geofence.center, point, func.coalesce(Geofence.radius_m, 0)),
            ),
        )
        .order_by(Geofence.name)
    )).all())


# ── administrative boundaries (global reference data) ───────────────────────

async def list_boundaries(
    db: AsyncSession, *, level: str | None = None, parent_id: int | None = None,
    q: str | None = None, pincode: str | None = None, limit: int = 100,
) -> list[AdminBoundary]:
    stmt = select(AdminBoundary).order_by(AdminBoundary.name).limit(limit)
    if level:
        stmt = stmt.where(AdminBoundary.level == level)
    if parent_id:
        stmt = stmt.where(AdminBoundary.parent_id == parent_id)
    if pincode:
        stmt = stmt.where(AdminBoundary.pincode == pincode)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(AdminBoundary.name.ilike(like), AdminBoundary.name_local.ilike(like)))
    return list((await db.scalars(stmt)).all())


async def create_boundary(db: AsyncSession, body: AdminBoundaryCreate) -> AdminBoundary:
    parent = None
    if body.parent_id:
        parent = await db.get(AdminBoundary, body.parent_id)
        if parent is None:
            raise NotFoundError(f"Parent boundary {body.parent_id} not found")
    slug = _slug(body.name)
    boundary = AdminBoundary(
        **body.model_dump(exclude={"centroid", "custom_attributes", "level"}, exclude_none=True),
        level=body.level.value,
        path=f"{parent.path if parent else '/'}{slug}/",
        depth=(parent.depth + 1) if parent else 0,
        custom_attributes=body.custom_attributes or {},
    )
    if body.centroid:
        boundary.centroid = _point(body.centroid.latitude, body.centroid.longitude)
    db.add(boundary)
    await db.flush()
    return boundary


async def boundary_for_point(db: AsyncSession, *, latitude: float, longitude: float) -> AdminBoundary | None:
    """The smallest administrative area covering a point. Resolved once per
    place and then cached on it — ``ST_Covers`` over district polygons is not
    a per-request query."""
    point = _point(latitude, longitude)
    return await db.scalar(
        select(AdminBoundary)
        .where(AdminBoundary.boundary.isnot(None), func.ST_Covers(AdminBoundary.boundary, point))
        .order_by(AdminBoundary.depth.desc())
        .limit(1)
    )


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-")


# ── place relationships ─────────────────────────────────────────────────────

async def relate_places(
    db: AsyncSession, place_ref: str, body: Any, *, actor_id: int | None = None,
) -> PlaceRelationship:
    """Create a relation and compute its metrics NOW.

    Distance and bearing are written once, here, from the two points — not by
    a trigger that recomputes them with correlated subqueries on every row
    that happens to be touched.
    """
    organization_id = await require_organization(db)
    source = await get_place(db, place_ref)
    target = await get_place(db, body.related_place)
    if source.id == target.id:
        raise GeoRuleError("A place cannot be related to itself")

    distance_m = bearing_deg = None
    if source.coordinates is not None and target.coordinates is not None:
        distance_m, bearing_deg = (await db.execute(text(
            "SELECT ST_Distance(a.coordinates, b.coordinates), "
            "       degrees(ST_Azimuth(a.coordinates::geometry, b.coordinates::geometry)) "
            "FROM geo.places a, geo.places b WHERE a.id = :a AND b.id = :b"
        ), {"a": source.id, "b": target.id})).one()

    relation = PlaceRelationship(
        organization_id=organization_id,
        place_id=source.id,
        related_place_id=target.id,
        relationship_type=body.relationship_type.value,
        transport_mode=body.transport_mode.value,
        is_bidirectional=body.is_bidirectional,
        sequence_number=body.sequence_number,
        duration_s=body.duration_s,
        routing_metadata=body.routing_metadata,
        distance_m=float(distance_m) if distance_m is not None else None,
        bearing_deg=float(bearing_deg) % 360 if bearing_deg is not None else None,
    )
    db.add(relation)
    await db.flush()
    return relation


async def list_relationships(db: AsyncSession, place_ref: str) -> list[PlaceRelationship]:
    place = await get_place(db, place_ref)
    return list((await db.scalars(
        select(PlaceRelationship)
        .where(or_(
            PlaceRelationship.place_id == place.id,
            PlaceRelationship.related_place_id == place.id,
        ))
        .order_by(PlaceRelationship.sequence_number.nulls_last(), PlaceRelationship.id)
    )).all())


# ── Zoho projection ─────────────────────────────────────────────────────────

async def upsert_place_from_zoho_location(db: AsyncSession, location: Any) -> Place | None:
    """Project a synced ``zoho_locations`` row into a usable place.

    The mirror records what Zoho said; this makes it addressable by the rest
    of the platform. Zoho owns the postal fields here
    (``ZOHO_OWNED_PLACE_FIELDS``), so a local edit cannot fight the next sync.
    """
    zoho_id = getattr(location, "zoho_id", None)
    if not zoho_id:
        return None
    organization_id = getattr(location, "organization_id", None) or await require_organization(db)

    place = await db.scalar(select(Place).where(Place.zoho_id == str(zoho_id)).limit(1))
    if place is None:
        place = Place(
            zoho_id=str(zoho_id), kind=PlaceKind.WAREHOUSE.value,
            tenant_id=location.tenant_id, organization_id=organization_id,
        )
        db.add(place)

    place.location_name = location.location_name
    place.is_primary = bool(location.is_primary)
    place.attention = location.address_attention
    place.street = location.address_street1
    place.street2 = location.address_street2
    place.city = location.address_city
    place.state = location.address_state
    place.state_code = location.address_state_code
    place.country = location.address_country or "India"
    place.phone = location.phone
    place.contact_email = location.email
    place.status = (
        PlaceStatus.ACTIVE.value if (location.zoho_status or "active") == "active"
        else PlaceStatus.ARCHIVED.value
    )
    place.formatted_address = compose_address(place)

    if location.parent_location_id:
        parent_id = await db.scalar(
            select(Place.id).where(Place.zoho_id == str(location.parent_location_id)).limit(1)
        )
        place.parent_location_id = parent_id                  # NULL until the parent syncs
    await db.flush()
    return place


def _jsonable(value: Any) -> Any:
    return value if isinstance(value, (str, int, float, bool, type(None), dict, list)) else str(value)
