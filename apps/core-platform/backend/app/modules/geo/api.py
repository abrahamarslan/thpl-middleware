"""Location hub HTTP API.

Four routers, mounted separately so the URLs read the way people think:

| Prefix | What |
|---|---|
| ``/api/locations`` | places — the canonical WHERE (not ``/api/zoho/locations``, which is the Zoho warehouse mirror) |
| ``/api/addresses`` | the polymorphic address book: any entity ↔ a place |
| ``/api/geofences`` | zones with an entry / exit / dwell policy |
| ``/api/admin-boundaries`` | administrative reference data (read-mostly) |

``{ref}`` is a uuid (preferred) or the numeric id. Every route is scoped to
the caller's tenant by app/database/tenancy.py; writes also need an
organization, taken from ``X-Organization-Id`` or resolved when the tenant
has exactly one.
"""

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.geo import service
from app.modules.geo.geocoding import service as geocoding
from app.modules.geo.geocoding.api import GeocodingUnavailableError
from app.modules.geo.geocoding.schema import PlaceGeocodeRequest
from app.modules.geo.geocoding.types import GeocodingUnavailable, ProviderNotConfigured
from app.modules.geo.scope import GeoRuleError
from app.modules.geo.schema import (
    AddressCreate,
    AddressOut,
    AddressUpdate,
    AdminBoundaryCreate,
    AdminBoundaryOut,
    GeofenceCreate,
    GeofenceOut,
    GeofenceUpdate,
    PlaceCreate,
    PlaceOut,
    PlaceRelationshipCreate,
    PlaceRelationshipOut,
    PlaceSlim,
    PlaceUpdate,
    PlaceVerify,
)
from app.modules.tenants.deps import TenantAdmin
from app.modules.users.deps import CurrentUser

places_router = APIRouter()
addresses_router = APIRouter()
geofences_router = APIRouter()
boundaries_router = APIRouter()

_M = "geo"


# ── places ──────────────────────────────────────────────────────────────────

@places_router.get("", response_model=ResponseModel[list[PlaceSlim]])
async def list_places(
    _: CurrentUser, db: DBSession,
    kind: str | None = Query(None, max_length=32),
    status: str | None = Query(None, pattern="^(active|archived|invalid)$"),
    q: str | None = Query(None, max_length=100, description="name, street, city or landmark"),
    postal_code: str | None = Query(None, max_length=16),
    verified: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_places(
        db, kind=kind, status=status, q=q, postal_code=postal_code, verified=verified,
        page=page, page_size=page_size,
    )
    return ResponseModel.ok(data=[PlaceSlim.model_validate(r) for r in rows])


@places_router.get("/nearby", response_model=ResponseModel[list[PlaceSlim]])
async def nearby(
    _: CurrentUser, db: DBSession,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(1000, gt=0, le=200_000),
    kind: str | None = Query(None, max_length=32),
    limit: int = Query(25, ge=1, le=100),
):
    """Places within a radius, nearest first."""
    rows = await service.nearby_places(
        db, latitude=latitude, longitude=longitude, radius_m=radius_m, kind=kind, limit=limit,
    )
    return ResponseModel.ok(data=[PlaceSlim.model_validate(r) for r in rows])


@places_router.post("", response_model=ResponseModel[PlaceOut], status_code=201)
async def create_place(
    user: CurrentUser, db: DBSession, body: PlaceCreate,
    reuse_duplicates: bool = Query(True, description="Return the existing place when one is within 25 m"),
):
    place = await service.create_place(db, body, actor_id=user.id, reuse_duplicates=reuse_duplicates)
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_created",
                            name=place.location_name or place.formatted_address or str(place.uuid))


@places_router.get("/{ref}", response_model=ResponseModel[PlaceOut])
async def get_place(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=PlaceOut.model_validate(await service.get_place(db, ref)))


@places_router.patch("/{ref}", response_model=ResponseModel[PlaceOut])
async def update_place(user: CurrentUser, db: DBSession, ref: str, body: PlaceUpdate):
    place = await service.update_place(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_updated",
                            name=place.location_name or str(place.uuid))


@places_router.post("/{ref}/geocode", response_model=ResponseModel[PlaceOut])
async def geocode_place(_: CurrentUser, db: DBSession, ref: str, body: PlaceGeocodeRequest):
    """Fill this place's coordinates from its postal fields.

    Sets `verification_status` to `geocoded_only` and leaves `is_verified`
    false: a provider returned a point, which is not the same as somebody
    confirming the door. On a Zoho-linked place only the position and the
    provenance are written — Zoho owns the address lines.
    """
    place = await service.get_place(db, ref)
    try:
        place, outcome = await geocoding.geocode_place(db, place, provider=body.provider)
    except (GeocodingUnavailable, ProviderNotConfigured) as exc:
        raise GeocodingUnavailableError(str(exc)) from exc
    if outcome.best is None:
        raise GeoRuleError(
            "No provider could find this address.",
            data={"providers_tried": outcome.providers_tried, "errors": outcome.errors},
        )
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_geocoded",
                            name=place.location_name or str(place.uuid))


@places_router.post("/{ref}/reverse-geocode", response_model=ResponseModel[PlaceOut])
async def reverse_geocode_place(_: CurrentUser, db: DBSession, ref: str, body: PlaceGeocodeRequest):
    """Fill this place's postal fields from its coordinates."""
    place = await service.get_place(db, ref)
    try:
        place, outcome = await geocoding.reverse_geocode_place(db, place, provider=body.provider)
    except (GeocodingUnavailable, ProviderNotConfigured) as exc:
        raise GeocodingUnavailableError(str(exc)) from exc
    if outcome.best is None:
        raise GeoRuleError(
            "No provider could name this point.",
            data={"providers_tried": outcome.providers_tried, "errors": outcome.errors},
        )
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_geocoded",
                            name=place.location_name or str(place.uuid))


@places_router.post("/{ref}/verify", response_model=ResponseModel[PlaceOut])
async def verify_place(user: CurrentUser, db: DBSession, ref: str, body: PlaceVerify):
    place = await service.verify_place(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_verified",
                            name=place.location_name or str(place.uuid))


@places_router.post("/{ref}/archive", response_model=ResponseModel[PlaceOut])
async def archive_place(user: CurrentUser, db: DBSession, ref: str,
                        reason: str = Query(..., min_length=3, max_length=500)):
    place = await service.archive_place(db, ref, reason=reason, actor_id=user.id)
    return ResponseModel.ok(data=PlaceOut.model_validate(place), module=_M, msg_key="place_archived",
                            name=place.location_name or str(place.uuid))


@places_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_place(admin: TenantAdmin, db: DBSession, ref: str,
                       reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_place(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="place_deleted", name=ref)


@places_router.get("/{ref}/addresses", response_model=ResponseModel[list[AddressOut]])
async def place_addresses(_: CurrentUser, db: DBSession, ref: str):
    """Who uses this place — read this before archiving one."""
    place = await service.get_place(db, ref)
    rows = await service.list_addresses(db, place=place.uuid, current_only=False)
    return ResponseModel.ok(data=[AddressOut.model_validate(r) for r in rows])


@places_router.get("/{ref}/relationships", response_model=ResponseModel[list[PlaceRelationshipOut]])
async def place_relationships(_: CurrentUser, db: DBSession, ref: str):
    rows = await service.list_relationships(db, ref)
    return ResponseModel.ok(data=[PlaceRelationshipOut.model_validate(r) for r in rows])


@places_router.post("/{ref}/relationships", response_model=ResponseModel[PlaceRelationshipOut],
                    status_code=201)
async def relate_places(user: CurrentUser, db: DBSession, ref: str, body: PlaceRelationshipCreate):
    relation = await service.relate_places(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=PlaceRelationshipOut.model_validate(relation), module=_M,
                            msg_key="relationship_created")


# ── addresses ───────────────────────────────────────────────────────────────

@addresses_router.get("", response_model=ResponseModel[list[AddressOut]])
async def list_addresses(
    _: CurrentUser, db: DBSession,
    owner_type: str | None = Query(None, max_length=50),
    owner_id: int | None = Query(None, gt=0),
    link_type: str | None = Query(None, max_length=20),
    current_only: bool = Query(True, description="false also returns closed (superseded) windows"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_addresses(
        db, owner_type=owner_type, owner_id=owner_id, link_type=link_type,
        current_only=current_only, page=page, page_size=page_size,
    )
    return ResponseModel.ok(data=[AddressOut.model_validate(r) for r in rows])


@addresses_router.get("/history", response_model=ResponseModel[list[AddressOut]])
async def history(
    _: CurrentUser, db: DBSession,
    owner_type: str = Query(..., max_length=50),
    owner_id: int = Query(..., gt=0),
    link_type: str | None = Query(None, max_length=20),
):
    """Every address this owner has held, newest window first — closed and
    detached ones included."""
    rows = await service.address_history(db, owner_type=owner_type, owner_id=owner_id, link_type=link_type)
    return ResponseModel.ok(data=[AddressOut.model_validate(r) for r in rows])


@addresses_router.post("", response_model=ResponseModel[AddressOut], status_code=201)
async def attach_address(user: CurrentUser, db: DBSession, body: AddressCreate):
    """Attach an address to any entity — pass an existing ``place`` uuid or a
    ``new_place`` to create and link in one call. ``freeze: true`` copies it
    into an immutable snapshot, which is what a document needs."""
    link = await service.attach_address(db, body, actor_id=user.id)
    return ResponseModel.ok(data=AddressOut.model_validate(link), module=_M, msg_key="address_attached",
                            owner=f"{link.owner_type} {link.owner_id}")


@addresses_router.get("/{ref}", response_model=ResponseModel[AddressOut])
async def get_address(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=AddressOut.model_validate(await service.get_address(db, ref)))


@addresses_router.patch("/{ref}", response_model=ResponseModel[AddressOut])
async def update_address(user: CurrentUser, db: DBSession, ref: str, body: AddressUpdate):
    link = await service.update_address(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=AddressOut.model_validate(link), module=_M, msg_key="address_updated",
                            owner=f"{link.owner_type} {link.owner_id}")


@addresses_router.post("/{ref}/verify", response_model=ResponseModel[AddressOut])
async def verify_address(user: CurrentUser, db: DBSession, ref: str, body: PlaceVerify):
    link = await service.verify_address(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=AddressOut.model_validate(link), module=_M, msg_key="address_verified",
                            owner=f"{link.owner_type} {link.owner_id}")


@addresses_router.delete("/{ref}", response_model=ResponseModel[None])
async def detach_address(user: CurrentUser, db: DBSession, ref: str,
                         reason: str = Query(..., min_length=3, max_length=500)):
    await service.detach_address(db, ref, reason=reason, actor_id=user.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="address_detached", owner=ref)


# ── geofences ───────────────────────────────────────────────────────────────

@geofences_router.get("", response_model=ResponseModel[list[GeofenceOut]])
async def list_geofences(
    _: CurrentUser, db: DBSession,
    fence_type: str | None = Query(None, max_length=32),
    status: str | None = Query("active", pattern="^(active|suspended|archived)$"),
):
    rows = await service.list_geofences(db, fence_type=fence_type, status=status)
    return ResponseModel.ok(data=[GeofenceOut.model_validate(r) for r in rows])


@geofences_router.get("/containing", response_model=ResponseModel[list[GeofenceOut]])
async def containing(
    _: CurrentUser, db: DBSession,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """Which active fences hold this point (polygons and circles alike)."""
    rows = await service.fences_containing(db, latitude=latitude, longitude=longitude)
    return ResponseModel.ok(data=[GeofenceOut.model_validate(r) for r in rows])


@geofences_router.post("", response_model=ResponseModel[GeofenceOut], status_code=201)
async def create_geofence(admin: TenantAdmin, db: DBSession, body: GeofenceCreate):
    fence = await service.create_geofence(db, body, actor_id=admin.id)
    return ResponseModel.ok(data=GeofenceOut.model_validate(fence), module=_M, msg_key="geofence_created",
                            name=fence.name)


@geofences_router.get("/{ref}", response_model=ResponseModel[GeofenceOut])
async def get_geofence(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=GeofenceOut.model_validate(await service.get_geofence(db, ref)))


@geofences_router.patch("/{ref}", response_model=ResponseModel[GeofenceOut])
async def update_geofence(admin: TenantAdmin, db: DBSession, ref: str, body: GeofenceUpdate):
    fence = await service.update_geofence(db, ref, body, actor_id=admin.id)
    return ResponseModel.ok(data=GeofenceOut.model_validate(fence), module=_M, msg_key="geofence_updated",
                            name=fence.name)


@geofences_router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_geofence(admin: TenantAdmin, db: DBSession, ref: str,
                          reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_geofence(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="geofence_deleted", name=ref)


# ── administrative boundaries ───────────────────────────────────────────────

@boundaries_router.get("", response_model=ResponseModel[list[AdminBoundaryOut]])
async def list_boundaries(
    _: CurrentUser, db: DBSession,
    level: str | None = Query(None, max_length=32),
    parent_id: int | None = Query(None, gt=0),
    q: str | None = Query(None, max_length=100),
    pincode: str | None = Query(None, max_length=16),
    limit: int = Query(100, ge=1, le=500),
):
    """Reference data for address forms: states, districts, cities, PIN codes.
    Shared by every tenant — see the module docstring for why it is global."""
    rows = await service.list_boundaries(db, level=level, parent_id=parent_id, q=q,
                                         pincode=pincode, limit=limit)
    return ResponseModel.ok(data=[AdminBoundaryOut.model_validate(r) for r in rows])


@boundaries_router.get("/resolve", response_model=ResponseModel[AdminBoundaryOut | None])
async def resolve_boundary(
    _: CurrentUser, db: DBSession,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """The smallest administrative area covering a point."""
    boundary = await service.boundary_for_point(db, latitude=latitude, longitude=longitude)
    return ResponseModel.ok(data=AdminBoundaryOut.model_validate(boundary) if boundary else None)


@boundaries_router.post("", response_model=ResponseModel[AdminBoundaryOut], status_code=201)
async def create_boundary(_: TenantAdmin, db: DBSession, body: AdminBoundaryCreate):
    boundary = await service.create_boundary(db, body)
    return ResponseModel.ok(data=AdminBoundaryOut.model_validate(boundary), module=_M,
                            msg_key="boundary_created", name=boundary.name)
