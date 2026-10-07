"""Shift cards — a page of shifts with everything the app renders, in a CONSTANT number of queries.

``shift_cards(db, shifts)`` adds, per shift: the hub (code, name), the template (code, name), the
start/end endpoints as the app shows them (name, address, coordinates, fence radius / uuid,
enforcement) and the stop counts. Each is ONE batched query for the whole page (hubs, templates,
places + their active fences, stop counts) — the N+1 test pins it. Details add the captured start/end
fixes (``captured_points``) and the fence pack (``fence_pack``).

A polygon fence is presented as its minimum enclosing circle (``ST_MinimumBoundingRadius``) — what
Android's GeofencingClient can register; the server still verifies against the polygon.
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.endpoints import SIDES, EndpointValue
from app.modules.fieldops.enums import EndpointMode
from app.modules.fieldops.schema import CapturedPoint, FenceOut, ShiftOut, ShiftSlim, StopOut

DEFAULT_RADIUS_M = 100.0


def _loaded(row: Any) -> dict[str, Any]:
    """The row's LOADED attributes (a ``load_only`` list row must never lazy-load under AsyncSession)."""
    return {k: v for k, v in inspect(row).dict.items() if not k.startswith("_")}


async def places_with_fences(db: AsyncSession, place_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not place_ids:
        return {}
    rows = (await db.execute(text("""
        SELECT p.id, p.uuid, p.location_name, p.formatted_address, p.latitude, p.longitude,
               f.uuid AS fence_uuid, f.radius_m AS fence_radius,
               CASE WHEN f.boundary IS NOT NULL THEN (ST_MinimumBoundingRadius(f.boundary::geometry)).radius END
                   AS polygon_radius_deg,
               CASE WHEN f.boundary IS NOT NULL THEN ST_Y((ST_MinimumBoundingRadius(f.boundary::geometry)).center) END
                   AS polygon_lat,
               CASE WHEN f.boundary IS NOT NULL THEN ST_X((ST_MinimumBoundingRadius(f.boundary::geometry)).center) END
                   AS polygon_lng,
               CASE WHEN f.center IS NOT NULL THEN ST_Y(f.center::geometry) END AS circle_lat,
               CASE WHEN f.center IS NOT NULL THEN ST_X(f.center::geometry) END AS circle_lng
          FROM geo.places p
          LEFT JOIN LATERAL (
              SELECT g.uuid, g.radius_m, g.boundary, g.center FROM geo.geofences g
               WHERE g.place_id = p.id AND g.status = 'active' AND g.deleted_at IS NULL
                 AND g.deactivation_date IS NULL
               ORDER BY (g.boundary IS NOT NULL) DESC, g.id LIMIT 1) f ON true
         WHERE p.id = ANY(CAST(:ids AS bigint[]))
    """), {"ids": list(place_ids)})).all()
    out = {}
    for r in rows:
        radius = float(r.fence_radius) if r.fence_radius is not None else (
            float(r.polygon_radius_deg) * 111_320 if r.polygon_radius_deg is not None else None)
        out[r.id] = {
            "uuid": r.uuid, "name": r.location_name, "address": r.formatted_address,
            "latitude": float(r.latitude) if r.latitude is not None else None,
            "longitude": float(r.longitude) if r.longitude is not None else None,
            "fence_uuid": r.fence_uuid, "fence_radius_m": radius,
            "fence_lat": r.polygon_lat if r.polygon_lat is not None else r.circle_lat,
            "fence_lng": r.polygon_lng if r.polygon_lng is not None else r.circle_lng,
        }
    return out


async def hubs_by_id(db: AsyncSession, ids: set[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    rows = (await db.execute(text("SELECT id, code, name, place_id FROM hubs WHERE id = ANY(CAST(:ids AS int[]))"),
                             {"ids": list(ids)})).all()
    return {r.id: {"id": r.id, "code": r.code, "name": r.name, "place_id": r.place_id} for r in rows}


def endpoint_out(value: EndpointValue, *, hubs: dict, places: dict, default_radius: float) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": value.mode}
    if value.is_anywhere:
        return out
    hub = hubs.get(value.hub_id) if value.hub_id else None
    place_id = value.place_id or (hub["place_id"] if hub else None)
    place = places.get(place_id) if place_id else None
    if hub:
        out.update(hub_id=hub["id"], hub_code=hub["code"], name=hub["name"])
    if place:
        out.update(place_uuid=place["uuid"], name=out.get("name") or place["name"], address=place["address"],
                   latitude=place["latitude"], longitude=place["longitude"], geofence_uuid=place["fence_uuid"])
        out["radius_m"] = float(value.radius_m) if value.radius_m else (place["fence_radius_m"] or default_radius)
    out["geofence_enforcement"] = value.enforcement
    return out


async def _context(db: AsyncSession, rows: list[Any]) -> dict[str, Any]:
    hub_ids: set[int] = set()
    template_ids: set[int] = set()
    for row in rows:
        data = _loaded(row) if not isinstance(row, dict) else row
        if data.get("hub_id"):
            hub_ids.add(data["hub_id"])
        if data.get("template_id"):
            template_ids.add(data["template_id"])
        for side in SIDES:
            if data.get(f"{side}_hub_id"):
                hub_ids.add(data[f"{side}_hub_id"])
    hubs = await hubs_by_id(db, hub_ids)
    place_ids = {h["place_id"] for h in hubs.values() if h["place_id"]}
    for row in rows:
        data = _loaded(row) if not isinstance(row, dict) else row
        for side in SIDES:
            if data.get(f"{side}_place_id"):
                place_ids.add(data[f"{side}_place_id"])
    places = await places_with_fences(db, place_ids)
    templates = {}
    if template_ids:
        templates = {r.id: {"uuid": r.uuid, "code": r.code, "name": r.name} for r in (await db.execute(text(
            "SELECT id, uuid, code, name FROM fieldops.shift_templates WHERE id = ANY(CAST(:ids AS bigint[]))"),
            {"ids": list(template_ids)})).all()}
    return {"hubs": hubs, "places": places, "templates": templates}


async def stop_counts(db: AsyncSession, shift_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not shift_ids:
        return {}
    rows = (await db.execute(text("""
        SELECT shift_id, count(*) FILTER (WHERE source = 'planned') AS total,
               count(*) FILTER (WHERE source = 'planned' AND status = 'completed') AS done
          FROM fieldops.visits
         WHERE shift_id = ANY(CAST(:ids AS bigint[])) AND deleted_at IS NULL AND status <> 'cancelled'
         GROUP BY shift_id
    """), {"ids": shift_ids})).all()
    return {r.shift_id: (int(r.total), int(r.done)) for r in rows}


def _card(data: dict[str, Any], ctx: dict[str, Any], counts: dict) -> dict[str, Any]:
    radius = float((data.get("policy_snapshot") or {}).get("default_visit_radius_m") or DEFAULT_RADIUS_M)
    for side in SIDES:
        value = EndpointValue(data.get(f"{side}_mode") or EndpointMode.ANYWHERE.value, data.get(f"{side}_hub_id"),
                              data.get(f"{side}_place_id"), data.get(f"{side}_enforcement"),
                              data.get(f"{side}_radius_m"))
        data[f"{side}_location"] = endpoint_out(value, hubs=ctx["hubs"], places=ctx["places"], default_radius=radius)
    hub = ctx["hubs"].get(data.get("hub_id"))
    data["hub"] = {"id": hub["id"], "code": hub["code"], "name": hub["name"]} if hub else None
    data["template"] = ctx["templates"].get(data.get("template_id"))
    total, done = counts.get(data.get("id"), (0, 0))
    data["stops_total"], data["stops_completed"] = total, done
    return data


async def shift_cards(db: AsyncSession, rows: list[Any], *, detail: bool = False) -> list[ShiftSlim | ShiftOut]:
    if detail:
        for row in rows:                 # server defaults / onupdate columns expire on flush: load them, once
            if inspect(row).unloaded:
                await db.refresh(row)
    ctx = await _context(db, rows)
    counts = await stop_counts(db, [r.id for r in rows if getattr(r, "id", None)])
    model = ShiftOut if detail else ShiftSlim
    return [model.model_validate(_card(_loaded(r), ctx, counts)) for r in rows]


async def captured_points(db: AsyncSession, shift: Any) -> dict[str, CapturedPoint | None]:
    rows = (await db.execute(text("""
        SELECT DISTINCT ON (checkpoint_label) checkpoint_label, ST_Y(coordinates::geometry) AS lat,
               ST_X(coordinates::geometry) AS lng, accuracy_m, recorded_at, occurred_at, is_mock
          FROM fieldops.location_pings
         WHERE tenant_id = :t AND user_id = :u AND shift_uuid = :s
           AND checkpoint_label IN ('shift_start', 'shift_end') AND coordinates IS NOT NULL
         ORDER BY checkpoint_label, accuracy_m ASC NULLS LAST, occurred_at
    """), {"t": shift.tenant_id, "u": shift.user_id, "s": shift.uuid})).all()
    found = {r.checkpoint_label: CapturedPoint(latitude=r.lat, longitude=r.lng, accuracy_m=r.accuracy_m,
                                               recorded_at=r.recorded_at, occurred_at=r.occurred_at,
                                               is_mock=r.is_mock) for r in rows}
    return {"captured_start": found.get("shift_start"), "captured_end": found.get("shift_end")}


async def shift_detail(db: AsyncSession, shift: Any) -> ShiftOut:
    card = (await shift_cards(db, [shift], detail=True))[0]
    return card.model_copy(update=await captured_points(db, shift))


async def stops_and_fences(db: AsyncSession, shift: Any, card: ShiftOut) -> tuple[list[StopOut], list[FenceOut]]:
    """The shift's stops (planned visits, in sequence) and the fence pack for the app."""
    visits = (await db.execute(text("""
        SELECT id, uuid, sequence_in_plan, status, purpose, stop_code, external_ref, account_type, account_id,
               planned_start_at, started_at, ended_at, start_check, place_id
          FROM fieldops.visits
         WHERE shift_id = :s AND deleted_at IS NULL AND source = 'planned'
         ORDER BY sequence_in_plan NULLS LAST, planned_start_at NULLS LAST, id
    """), {"s": shift.id})).all()
    places = await places_with_fences(db, {v.place_id for v in visits if v.place_id})
    radius = float((shift.policy_snapshot or {}).get("default_visit_radius_m") or DEFAULT_RADIUS_M)
    stops, fences = [], []
    for v in visits:
        place = places.get(v.place_id)
        location = endpoint_out(EndpointValue(EndpointMode.PLACE.value, None, v.place_id), hubs={}, places=places,
                                default_radius=radius) if place else None
        stops.append(StopOut(uuid=v.uuid, sequence=v.sequence_in_plan, status=v.status, purpose=v.purpose,
                             stop_code=v.stop_code, external_ref=v.external_ref, account_type=v.account_type,
                             account_id=v.account_id, planned_start_at=v.planned_start_at, started_at=v.started_at,
                             ended_at=v.ended_at, start_check=v.start_check, location=location))
        if place and v.status in ("planned", "in_progress") and place["latitude"] is not None:
            fences.append(_fence("stop", place, radius, visit_uuid=v.uuid))
    for side in SIDES:
        loc = getattr(card, f"{side}_location")
        if loc is not None and loc.place_uuid is not None and loc.latitude is not None:
            fences.append(FenceOut(fence_id=loc.geofence_uuid or loc.place_uuid, kind=side, place_uuid=loc.place_uuid,
                                   latitude=loc.latitude, longitude=loc.longitude,
                                   radius_m=float(loc.radius_m or radius), enforcement=loc.geofence_enforcement))
    return stops, fences[:100]          # Android registers at most 100 geofences per app


def _fence(kind: str, place: dict, radius: float, *, visit_uuid: uuid_lib.UUID | None = None) -> FenceOut:
    lat = float(place["fence_lat"]) if place.get("fence_lat") is not None else place["latitude"]
    lng = float(place["fence_lng"]) if place.get("fence_lng") is not None else place["longitude"]
    return FenceOut(fence_id=place["fence_uuid"] or place["uuid"], kind=kind, place_uuid=place["uuid"],
                    visit_uuid=visit_uuid, latitude=lat, longitude=lng,
                    radius_m=float(place["fence_radius_m"] or radius))


async def virtual_card(db: AsyncSession, *, user_id: int, template: Any, occ: Any,
                       hub: dict | None) -> ShiftSlim:
    """A template occurrence nobody has started: shown in ``/me/shifts?upcoming`` with ``uuid = null``."""
    data: dict[str, Any] = {
        "uuid": None, "shift_code": None, "title": None, "work_type": template.work_type, "source": "template",
        "user_id": user_id, "shift_date": occ.day, "status": "scheduled", "review_status": "not_required",
        "planned_start_at": occ.planned_start_at, "planned_end_at": occ.planned_end_at, "started_at": None,
        "ended_at": None, "paused_since": None, "pause_count": 0, "wall_clock_minutes": None, "paid_minutes": None,
        "duration_basis": None, "hub_id": hub["id"] if hub else None, "template_id": template.id,
    }
    from app.modules.fieldops.service.templates import title_for

    data["title"] = title_for(template, occ.day)
    for side in SIDES:
        value = EndpointValue.of(template, side)
        if value.mode == EndpointMode.ASSIGNED_HUB.value and hub:
            value = EndpointValue(EndpointMode.HUB.value, hub["id"], hub["place_id"], value.enforcement, value.radius_m)
        for name, v in value.as_dict().items():
            data[f"{side}_{name}"] = v
    return ShiftSlim.model_validate(_card(data, await _context(db, [data]), {}))


__all__ = ["captured_points", "endpoint_out", "places_with_fences", "shift_cards", "shift_detail",
           "stops_and_fences", "virtual_card"]
