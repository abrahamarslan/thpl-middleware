"""The field app's API — ``/api/me/…``: one's OWN devices, shifts, pauses, visits, tasks and location.

Every route needs ``fieldops.field_work:use`` (granted to ``member``). What the worker MUST do
(shift required, consent, selfie, geofence enforcement) is their work policy, applied by the
services. Telephonic / video visits additionally need ``fieldops.telephonic_visit:create``.

Offline-first contract (docs/fieldops/implementation-of-shift-visits-system.md §18):

* entities carry the client's UUIDv7 — a replayed create returns the existing entity (200
  instead of 201);
* mutations accept ``X-Idempotency-Key`` — a replay returns the stored response;
* every request may carry the device's clocks at send (``X-Device-Sent-At``,
  ``X-Device-Elapsed-Ms``, ``X-Device-Boot-Count``) and ``X-Device-Session``;
  business times are derived from them (clock.py), never from the receipt time alone.

``PATCH/GET /me/location`` (the pre-fieldops single-fix endpoints) live here now: a one-item
batch through the same ingest, so older app builds keep working and write the one stream.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from app.common.client_info import ClientInfoDep
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.fieldops import cards, crud, jobs
from app.modules.fieldops.clock import business_date
from app.modules.fieldops.deps import DeviceClock, IdempotencyKeyDep, request_id
from app.modules.fieldops.enums import Channel
from app.modules.fieldops.errors import FieldOpsRuleError
from app.modules.fieldops.schema import (
    CurrentOut,
    DeviceEventsIn,
    DeviceEventsResultOut,
    DeviceOut,
    DeviceRegisteredOut,
    DeviceRegisterIn,
    DeviceSessionOut,
    EffectivePolicyOut,
    MyShiftDetailOut,
    ParticipantOut,
    PauseOut,
    PingBatchIn,
    PingBatchResultOut,
    ShiftEndIn,
    ShiftHandoverIn,
    ShiftOut,
    ShiftPauseIn,
    ShiftResumeIn,
    ShiftSlim,
    ShiftStartIn,
    TaskIn,
    TaskOut,
    TaskVoidIn,
    VisitCancelIn,
    VisitEndIn,
    VisitJoinIn,
    VisitOut,
    VisitSlim,
    VisitStartIn,
    VisitStartPlannedIn,
)
from app.modules.fieldops.service import (  # noqa: F401 — session_rules / consent_hooks register on import
    consent_hooks,
    devices,
    ingest,
    policy,
    session_rules,
    shifts,
    tasks,
    visits,
)
from app.modules.fieldops.service.common import org_timezone
from app.modules.fieldops.service.context import Act
from app.modules.idempotency import service as idempotency
from app.modules.rbac.deps import GrantsDep, Perm
from app.modules.users.deps import CurrentUser
from app.modules.users.schema import LiveLocationOut, LocationUpdate

router = APIRouter()
#: ``/api/auth/me/location`` — the historical alias of ``/api/me/location``, kept for old app builds.
auth_alias_router = APIRouter()

FieldWorker = Perm("fieldops.field_work:use")
TELEPHONIC = "fieldops.telephonic_visit:create"


def _act(user, send, request: Request, key: uuid_lib.UUID | None) -> Act:
    return Act(user=user, send=send, request_id=request_id(request), idempotency_key=key)


async def _device_id(db, user, send) -> int | None:
    session = await devices.resolve_session(db, user, send.session_uuid)
    return session.device_id if session else None


# ── devices ─────────────────────────────────────────────────────────────────────

@router.post("/devices", response_model=ResponseModel[DeviceRegisteredOut])
async def register_device(user: FieldWorker, db: DBSession, body: DeviceRegisterIn):
    """Register this installation and its app session (call on every launch). ``warnings`` lists the
    capability problems that will break tracking — show them before the shift, not after."""
    device, session, warnings = await devices.register(db, user, body)
    return ResponseModel(data=DeviceRegisteredOut(device=DeviceOut.model_validate(device),
                                                  session=DeviceSessionOut.model_validate(session),
                                                  warnings=warnings))


@router.post("/device-events", response_model=ResponseModel[DeviceEventsResultOut])
async def device_events(user: FieldWorker, db: DBSession, send: DeviceClock, body: DeviceEventsIn):
    """Tracking-health events (GPS off, permission changed, app restarted after being killed …)."""
    accepted, duplicates = await devices.record_events(db, user, send, body)
    return ResponseModel(data=DeviceEventsResultOut(accepted=accepted, duplicates=duplicates))


# ── policy / current state ─────────────────────────────────────────────────────

@router.get("/fieldops/policy", response_model=ResponseModel[EffectivePolicyOut])
async def my_policy(user: FieldWorker, db: DBSession, grants: GrantsDep):
    """The policy that applies to me (every flat value), plus what my role may do (e.g. telephonic visits)."""
    effective = await policy.resolve_policy(db, user)
    return ResponseModel(data=EffectivePolicyOut(
        policy_id=effective.policy_id, policy_uuid=effective.policy_uuid, values=effective.snapshot(),
        can_telephonic=await grants.allows(db, TELEPHONIC), layers=effective.layer_uuids, epoch=effective.epoch,
    ))


@router.get("/fieldops/config", response_model=ResponseModel[dict],
            responses={304: {"description": "Not modified (If-None-Match matched the ETag)"}})
async def my_config(user: FieldWorker, db: DBSession,
                    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None):
    """The field app's configuration (Android ``LocationConfig`` schema v5), resolved from the policy
    layers for me — and, during a shift, its hub/beat, with the shift's frozen obligations.

    ``config_version`` never decreases: apply a config when ``config_version >= applied`` and the ETag
    differs. Send ``If-None-Match`` on refresh: an unchanged config is a bodyless ``304``."""
    from app.modules.fieldops.policy.render import etag

    body, meta = await policy.client_config(db, user)
    tag = etag(body)
    headers = {"ETag": tag, "Cache-Control": "private, max-age=0, must-revalidate"}
    if if_none_match and if_none_match.strip() == tag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=ResponseModel(data=body, meta=meta).model_dump(mode="json"), headers=headers)


@router.get("/fieldops/current", response_model=ResponseModel[CurrentOut])
async def my_current(user: FieldWorker, db: DBSession):
    """My open shift, its open pause and my in-progress visit — the app's resume call after a restart."""
    from app.modules.compliance.consents import live

    shift, pause, visit = await crud.current_of(db, user.id)
    location = await live(db, user.id, "location_tracking")
    effective = await policy.resolve_policy(db, user, shift=shift)
    return ResponseModel(data=CurrentOut(
        shift=await cards.shift_detail(db, shift) if shift else None,
        open_pause=PauseOut.model_validate(pause) if pause else None,
        visit=VisitOut.model_validate(visit) if visit else None,
        consent={"location_tracking": {"given": bool(location),
                                       "version": location[0].consent_text_version if location else None,
                                       "required": bool(effective.require_location_consent)}},
    ))


# ── shifts ──────────────────────────────────────────────────────────────────────

@router.post("/shifts", response_model=ResponseModel[ShiftOut], status_code=201)
async def start_shift(user: FieldWorker, db: DBSession, send: DeviceClock, key: IdempotencyKeyDep,
                      request: Request, body: ShiftStartIn) -> JSONResponse:
    """Start my shift. 201 created · 200 replay of the same uuid · 409 ``shift_already_active`` ·
    422 ``location_required`` / ``location_consent_required`` / ``device_not_registered`` / …"""
    async def handler():
        device_id = await _device_id(db, user, send)
        shift, created = await shifts.start_shift(db, _act(user, send, request, key), body, device_id=device_id)
        return ResponseModel(data=await cards.shift_detail(db, shift),
                             msg="Shift started" if created else "Shift already started"), 201 if created else 200

    return await idempotency.run(db, user=user, key=key, route="POST /me/shifts",
                                 payload=body.model_dump(mode="json"), status_code=201, handler=handler,
                                 entity_type="shift")


@router.get("/shifts", response_model=ResponseModel[list[ShiftSlim]])
async def my_shifts(user: FieldWorker, db: DBSession, date_from: dt.date | None = None, date_to: dt.date | None = None,
                    status: str | None = None, upcoming: bool = False, limit: int = Query(31, ge=1, le=366)):
    """My shifts — open first, then scheduled (by planned start), then history (newest first).

    Each item carries the plan: ``title``, ``work_type``, planned window, ``start_location`` /
    ``end_location`` (mode, name, address, coordinates, fence radius, enforcement), the ``hub``,
    the ``template`` and the stop counts. With no date filter (or ``upcoming=true``), today's (and,
    within 12 h, tomorrow's) occurrence of my SHIFT TEMPLATE is included as a VIRTUAL entry with
    ``uuid: null`` and ``source: template`` — start it with a new uuid."""
    rows = await crud.my_shifts(db, user.id, date_from=date_from, date_to=date_to, limit=limit, status=status,
                                upcoming=upcoming)
    items = await cards.shift_cards(db, rows)
    if upcoming or (date_from is None and date_to is None and status is None):
        items = await shifts.virtual_entries(db, user) + items
    return ResponseModel(data=items)


@router.get("/shifts/{shift_uuid}", response_model=ResponseModel[MyShiftDetailOut])
async def my_shift(shift_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession):
    """One of my shifts with its captured start/end, its stops (planned visits, in order) and the FENCE PACK:
    circles to register with Android's GeofencingClient (``requestId = fence_id``; ≤ 100)."""
    from app.modules.fieldops.service.common import own_shift

    shift = await own_shift(db, user, shift_uuid)
    detail = await cards.shift_detail(db, shift)
    stops, fences = await cards.stops_and_fences(db, shift, detail)
    return ResponseModel(data=MyShiftDetailOut(shift=detail, stops=stops, fences=fences))


@router.post("/shifts/{shift_uuid}/handover", response_model=ResponseModel[ShiftOut])
async def handover_shift(shift_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                         request: Request, body: ShiftHandoverIn | None = None):
    """Move my OPEN shift to this device (I signed in on a new phone): fixes from here stop being
    ``foreign_device``. Needs ``X-Device-Session`` of a registered device."""
    device_id = await _device_id(db, user, send)
    shift = await shifts.handover(db, _act(user, send, request, None), shift_uuid, device_id=device_id)
    return ResponseModel(data=await cards.shift_detail(db, shift), msg="Shift moved to this device")


@router.post("/shifts/{shift_uuid}/pause", response_model=ResponseModel[PauseOut], status_code=201)
async def pause_shift(shift_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                      key: IdempotencyKeyDep, request: Request, body: ShiftPauseIn) -> JSONResponse:
    """Pause my shift (a break, prayer, a vehicle breakdown, no network …). No visit may start while
    paused; the policy says whether the pause is paid and whether tracking continues."""
    async def handler():
        pause = await shifts.pause_shift(db, _act(user, send, request, key), shift_uuid, body)
        return ResponseModel(data=PauseOut.model_validate(pause), msg="Shift paused")

    return await idempotency.run(db, user=user, key=key, route="POST /me/shifts/{uuid}/pause",
                                 payload={"shift": str(shift_uuid), **body.model_dump(mode="json")},
                                 status_code=201, handler=handler, entity_type="shift_pause")


@router.post("/shifts/{shift_uuid}/resume", response_model=ResponseModel[PauseOut])
async def resume_shift(shift_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                       key: IdempotencyKeyDep, request: Request, body: ShiftResumeIn) -> JSONResponse:
    async def handler():
        pause = await shifts.resume_shift(db, _act(user, send, request, key), shift_uuid, body)
        return ResponseModel(data=PauseOut.model_validate(pause), msg="Shift resumed")

    return await idempotency.run(db, user=user, key=key, route="POST /me/shifts/{uuid}/resume",
                                 payload={"shift": str(shift_uuid), **body.model_dump(mode="json")},
                                 status_code=200, handler=handler)


@router.post("/shifts/{shift_uuid}/end", response_model=ResponseModel[ShiftOut])
async def end_shift(shift_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                    key: IdempotencyKeyDep, request: Request, body: ShiftEndIn) -> JSONResponse:
    """End my shift. 409 ``visit_in_progress`` until the visit is ended; an open pause is closed."""
    async def handler():
        shift = await shifts.end_shift(db, _act(user, send, request, key), shift_uuid, body)
        jobs.enqueue(jobs.COMPUTE_METRICS, shift.id)
        return ResponseModel(data=await cards.shift_detail(db, shift), msg="Shift ended")

    return await idempotency.run(db, user=user, key=key, route="POST /me/shifts/{uuid}/end",
                                 payload={"shift": str(shift_uuid), **body.model_dump(mode="json")},
                                 status_code=200, handler=handler)


# ── visits ──────────────────────────────────────────────────────────────────────

@router.post("/visits", response_model=ResponseModel[VisitOut], status_code=201)
async def start_visit(user: FieldWorker, db: DBSession, grants: GrantsDep, send: DeviceClock, key: IdempotencyKeyDep,
                      request: Request, body: VisitStartIn) -> JSONResponse:
    """Start a visit. 201 · 200 replay · 403 remote channel without the permission · 409
    ``visit_in_progress`` / ``shift_paused`` · 422 ``shift_required`` / ``justification_required`` /
    ``outside_geofence`` / ``location_required``."""
    async def handler():
        can_remote = body.channel is Channel.FIELD or await grants.allows(db, TELEPHONIC)
        device_id = await _device_id(db, user, send)
        visit, created = await visits.start_visit(db, _act(user, send, request, key), body, can_remote=can_remote,
                                                  device_id=device_id)
        return ResponseModel(data=VisitOut.model_validate(visit),
                             msg="Visit started" if created else "Visit already started"), 201 if created else 200

    return await idempotency.run(db, user=user, key=key, route="POST /me/visits",
                                 payload=body.model_dump(mode="json"), status_code=201, handler=handler,
                                 entity_type="visit")


@router.post("/visits/{visit_uuid}/start", response_model=ResponseModel[VisitOut], status_code=201)
async def start_planned_visit(visit_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                              key: IdempotencyKeyDep, request: Request, body: VisitStartPlannedIn) -> JSONResponse:
    """Start a PLANNED visit — a stop of my shift ("Start Delivery"). The ``fix`` is the proof-of-presence
    capture (send the high-accuracy one-shot); verification and enforcement are those of any visit start.
    201 started · 200 replay · 409 ``visit_not_planned`` / ``shift_not_active`` / ``visit_in_progress`` ·
    422 ``justification_required`` / ``outside_geofence`` / ``mock_location_rejected``."""
    async def handler():
        device_id = await _device_id(db, user, send)
        visit, created = await visits.start_planned(db, _act(user, send, request, key), visit_uuid, body,
                                                    device_id=device_id)
        return ResponseModel(data=VisitOut.model_validate(visit),
                             msg="Visit started" if created else "Visit already started"), 201 if created else 200

    return await idempotency.run(db, user=user, key=key, route="POST /me/visits/{uuid}/start",
                                 payload=body.model_dump(mode="json"), status_code=201, handler=handler,
                                 entity_type="visit")


@router.get("/visits", response_model=ResponseModel[list[VisitSlim]])
async def my_visits(user: FieldWorker, db: DBSession, day: Annotated[dt.date | None, Query(alias="date")] = None):
    """My visits of a business day (organization timezone; default today)."""
    tz = await org_timezone(db, user.organization_id)
    day = day or business_date(dt.datetime.now(dt.UTC), tz)
    from zoneinfo import ZoneInfo

    start = dt.datetime.combine(day, dt.time.min, tzinfo=ZoneInfo(tz or "Asia/Kolkata"))
    rows = await crud.my_visits(db, user.id, day_start=start, day_end=start + dt.timedelta(days=1))
    return ResponseModel(data=[VisitSlim.model_validate(r) for r in rows])


@router.post("/visits/{visit_uuid}/end", response_model=ResponseModel[VisitOut])
async def end_visit(visit_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                    key: IdempotencyKeyDep, request: Request, body: VisitEndIn) -> JSONResponse:
    async def handler():
        visit = await visits.end_visit(db, _act(user, send, request, key), visit_uuid, body)
        jobs.enqueue(jobs.DETECT_DWELL, visit.id, countdown=300)
        return ResponseModel(data=VisitOut.model_validate(visit), msg="Visit ended")

    return await idempotency.run(db, user=user, key=key, route="POST /me/visits/{uuid}/end",
                                 payload={"visit": str(visit_uuid), **body.model_dump(mode="json")},
                                 status_code=200, handler=handler)


@router.post("/visits/{visit_uuid}/cancel", response_model=ResponseModel[VisitOut])
async def cancel_visit(visit_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                       key: IdempotencyKeyDep, request: Request, body: VisitCancelIn) -> JSONResponse:
    async def handler():
        visit = await visits.cancel_visit(db, _act(user, send, request, key), visit_uuid, body)
        return ResponseModel(data=VisitOut.model_validate(visit), msg="Visit cancelled")

    return await idempotency.run(db, user=user, key=key, route="POST /me/visits/{uuid}/cancel",
                                 payload={"visit": str(visit_uuid), **body.model_dump(mode="json")},
                                 status_code=200, handler=handler)


@router.post("/visits/{visit_uuid}/join", response_model=ResponseModel[ParticipantOut])
async def join_visit(visit_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                     request: Request, body: VisitJoinIn):
    """Joint working: join a colleague's visit in progress."""
    participant = await visits.join_visit(db, _act(user, send, request, None), visit_uuid, body)
    return ResponseModel(data=ParticipantOut.model_validate(participant))


@router.post("/visits/{visit_uuid}/tasks", response_model=ResponseModel[TaskOut], status_code=201)
async def submit_task(visit_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                      key: IdempotencyKeyDep, request: Request, body: TaskIn) -> JSONResponse:
    """Record what was done in the visit. The payload is validated per ``task_type``; a task after the
    visit ended is recorded (``after_visit_end``) within the policy's late window."""
    async def handler():
        task, created = await tasks.submit_task(db, _act(user, send, request, key), visit_uuid, body)
        return ResponseModel(data=TaskOut.model_validate(task),
                             msg="Task recorded" if created else "Task already recorded"), 201 if created else 200

    return await idempotency.run(db, user=user, key=key, route="POST /me/visits/{uuid}/tasks",
                                 payload={"visit": str(visit_uuid), **body.model_dump(mode="json")},
                                 status_code=201, handler=handler, entity_type="visit_task")


@router.post("/visit-tasks/{task_uuid}/void", response_model=ResponseModel[TaskOut])
async def void_task(task_uuid: uuid_lib.UUID, user: FieldWorker, db: DBSession, send: DeviceClock,
                    request: Request, body: TaskVoidIn):
    task = await tasks.void_task(db, _act(user, send, request, None), task_uuid, reason=body.reason)
    return ResponseModel(data=TaskOut.model_validate(task), msg="Task voided")


# ── the stream ──────────────────────────────────────────────────────────────────

@router.post("/location-pings", response_model=ResponseModel[PingBatchResultOut])
async def upload_pings(user: FieldWorker, db: DBSession, send: DeviceClock, body: PingBatchIn, request: Request):
    """Flush the offline queue: up to 500 fixes. ALWAYS 200 with per-item results: drop ``accepted``
    and ``duplicate`` items locally, drop ``rejected`` ones too (they cannot be fixed by retrying)."""
    session = await devices.resolve_session(db, user, send.session_uuid)
    result = await ingest.ingest_batch(db, user, send, body, session=session,
                                       not_after=getattr(request.state, "session_drain_not_after", None))
    return ResponseModel(data=result)


async def _legacy_fix(db: DBSession, user, send, body: LocationUpdate, client) -> LiveLocationOut:
    """One fix from the pre-fieldops endpoint → a one-item batch into the stream."""
    from sqlalchemy import select, update

    from app.modules.users.model import UserLiveLocation

    provider = {"gps": "gps", "network": "network", "manual": "manual"}.get(body.location_source or "", "fused")
    item = {
        "uuid": str(uuid_lib.uuid4()), "latitude": body.latitude, "longitude": body.longitude,
        "accuracy_m": body.accuracy_m, "altitude_m": body.altitude_m,
        "vertical_accuracy_m": body.altitude_accuracy_m, "heading_deg": body.heading_deg,
        "speed_mps": body.speed_mps, "provider": provider,
        "client_timestamp": body.recorded_at.isoformat() if body.recorded_at else None,
        "network_type": (body.network_type or None) and body.network_type[:10],
    }
    if provider == "manual":
        item["manual_reason"] = "manual location (legacy /me/location)"
    shift, _, visit = await crud.current_of(db, user.id)
    if shift is not None:
        item["shift_uuid"] = str(shift.uuid)
    if visit is not None:
        item["visit_uuid"] = str(visit.uuid)
    result = await ingest.ingest_batch(db, user, send, PingBatchIn(uuid=uuid_lib.uuid4(), pings=[item]),
                                       session=None)
    if result.rejected:
        raise FieldOpsRuleError("invalid_fix", result.results[0].reason or "The fix was rejected")
    legacy = {k: v for k, v in {
        "tracking_active": body.tracking_active, "background_tracking_enabled": body.background_tracking_enabled,
        "device_id": body.device_id, "device_type": body.device_type, "is_moving": body.is_moving,
        "altitude_accuracy_m": body.altitude_accuracy_m, "place_id": body.place_id,
        "ip_address": client.ip if client is not None else None,
    }.items() if v is not None}
    if legacy:
        await db.execute(update(UserLiveLocation).where(UserLiveLocation.user_id == user.id).values(**legacy))
    live = await db.scalar(select(UserLiveLocation).where(UserLiveLocation.user_id == user.id)
                           .execution_options(populate_existing=True))
    if not user.is_location_set:
        user.is_location_set = True
    await db.flush()
    return LiveLocationOut.from_row(live)


@router.patch("/location", response_model=ResponseModel[LiveLocationOut])
@auth_alias_router.patch("/me/location", response_model=ResponseModel[LiveLocationOut])
async def update_my_location(db: DBSession, user: CurrentUser, send: DeviceClock, body: LocationUpdate,
                             client: ClientInfoDep):
    """Report one position fix (legacy single-fix endpoint; new apps batch to ``/me/location-pings``)."""
    live = await _legacy_fix(db, user, send, body, client)
    return ResponseModel.ok(data=live, module="users", msg_key="location_recorded")


@router.get("/location", response_model=ResponseModel[LiveLocationOut | None])
@auth_alias_router.get("/me/location", response_model=ResponseModel[LiveLocationOut | None])
async def get_my_location(db: DBSession, user: CurrentUser):
    """My last known position (``null`` if never reported)."""
    from sqlalchemy import select

    from app.modules.users.model import UserLiveLocation

    live = await db.scalar(select(UserLiveLocation).where(UserLiveLocation.user_id == user.id))
    return ResponseModel(data=LiveLocationOut.from_row(live) if live else None)


__all__ = ["auth_alias_router", "router"]
