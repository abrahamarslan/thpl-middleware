"""Managers' API — ``/api/fieldops/…``: shifts, visits, tracks, the live map, anomalies, the
review queue and policy layers.

Two gates on every read of people's field data:

1. ``Perm(code[, target=…])`` — may the caller do this at all (at the row's organization)?
2. ``scope.visible`` — WHOSE rows: a team-scoped manager sees their teams and direct reports,
   not the whole tenant (the interim data scope; docs/fieldops/improvement-document.md D8).
   A row outside the caller's visible set is a 404, never a 403 (no existence oracle).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.fieldops import cards, crud, jobs
from app.modules.fieldops.deps import (
    anomaly_target,
    policy_target,
    shift_target,
    template_target,
    visit_target,
)
from app.modules.fieldops.errors import FieldOpsNotFound
from app.modules.fieldops.schema import (
    AnomalyOut,
    AnomalyResolveIn,
    LiveUserOut,
    LocationCheckOut,
    MetricsOut,
    ParticipantOut,
    PauseOut,
    PolicyLayerIn,
    PolicyLayerOut,
    PolicyLayerUpdate,
    PolicyLayerWriteOut,
    PolicyPreviewIn,
    ReviewIn,
    ReviewQueueOut,
    ShiftCorrectIn,
    ShiftDetailOut,
    ShiftOut,
    ShiftScheduleBulkIn,
    ShiftScheduleIn,
    ShiftScheduleUpdate,
    ShiftSlim,
    ShiftTemplateIn,
    ShiftTemplateOut,
    ShiftTemplateUpdate,
    StopsIn,
    TaskOut,
    TrackOut,
    TrackPoint,
    VisitCorrectIn,
    VisitDetailOut,
    VisitOut,
    VisitSlim,
)
from app.modules.fieldops.scope import Visible, visible
from app.modules.fieldops.service import anomalies, metrics, policy, shifts, templates, visits
from app.modules.rbac.deps import GrantsDep, Perm

router = APIRouter()


async def _visible(db, grants, user, code: str) -> Visible:
    return await visible(db, grants, code, actor_id=user.id)


def _ensure_visible(scope: Visible, row) -> None:
    if not scope.allows_user(row.user_id, row.organization_id):
        raise FieldOpsNotFound("Not found")


def _page(items: list, limit: int, offset: int) -> PageModel:
    return PageModel(items=items, page=offset // limit + 1 if limit else 1, page_size=limit,
                     has_more=len(items) == limit)


# ── shifts ──────────────────────────────────────────────────────────────────────

@router.get("/shifts", response_model=ResponseModel[PageModel[ShiftSlim]])
async def list_shifts(
    user: Perm("fieldops.shift:read"), db: DBSession, grants: GrantsDep,
    user_id: int | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
    status: str | None = None, review_status: str | None = None,
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
):
    scope = await _visible(db, grants, user, "fieldops.shift:read")
    rows = await crud.list_shifts(db, visible=scope, user_id=user_id, date_from=date_from, date_to=date_to,
                                  status=status, review_status=review_status, limit=limit, offset=offset)
    return ResponseModel(data=_page(await cards.shift_cards(db, rows), limit, offset))


@router.get("/shifts/{ref}", response_model=ResponseModel[ShiftDetailOut])
async def get_shift(ref: str, user: Perm("fieldops.shift:read", target=shift_target), db: DBSession,
                    grants: GrantsDep):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:read"), shift)
    stats = await crud.metrics_of(db, shift.id)
    return ResponseModel(data=ShiftDetailOut(
        shift=await cards.shift_detail(db, shift),
        pauses=[PauseOut.model_validate(p) for p in await crud.pauses_of(db, shift.id)],
        visits=[VisitSlim.model_validate(v) for v in await crud.visits_of_shift(db, shift.id)],
        metrics=MetricsOut.model_validate(stats) if stats else None,
        open_anomalies=[AnomalyOut.model_validate(a) for a in await crud.open_anomalies_of_shift(db, shift.id)],
    ))


@router.get("/shifts/{ref}/track", response_model=ResponseModel[TrackOut])
async def shift_track(ref: str, user: Perm("users.location:read", target=shift_target), db: DBSession,
                      grants: GrantsDep, simplify_m: float = Query(10.0, ge=0, le=500)):
    """The shift's fixes as points and a GeoJSON LineString (checkpoints always kept)."""
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "users.location:read"), shift)
    rows = await crud.track(db, shift, simplify_m=simplify_m)
    points = [TrackPoint(uuid=r.uuid, occurred_at=r.occurred_at, latitude=r.lat, longitude=r.lng,
                         accuracy_m=r.accuracy_m, kind=r.kind, checkpoint_label=r.checkpoint_label,
                         quality_flags=r.quality_flags) for r in rows]
    geojson = {"type": "Feature", "properties": {"shift_uuid": str(shift.uuid)},
               "geometry": {"type": "LineString", "coordinates": [[p.longitude, p.latitude] for p in points]}}
    return ResponseModel(data=TrackOut(shift_uuid=shift.uuid, points=points, geojson=geojson))


@router.get("/shifts/{ref}/metrics", response_model=ResponseModel[MetricsOut | None])
async def shift_metrics(ref: str, user: Perm("fieldops.shift:read", target=shift_target), db: DBSession,
                        grants: GrantsDep):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:read"), shift)
    stats = await crud.metrics_of(db, shift.id)
    return ResponseModel(data=MetricsOut.model_validate(stats) if stats else None)


@router.post("/shifts/{ref}/metrics/recompute", response_model=ResponseModel[MetricsOut | None])
async def recompute_metrics(ref: str, user: Perm("fieldops.shift:update", target=shift_target), db: DBSession,
                            grants: GrantsDep):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:update"), shift)
    stats = await metrics.compute_shift_metrics(db, shift.id)
    return ResponseModel(data=MetricsOut.model_validate(stats) if stats else None)


@router.patch("/shifts/{ref}", response_model=ResponseModel[ShiftOut])
async def correct_shift(ref: str, user: Perm("fieldops.shift:update", target=shift_target), db: DBSession,
                        grants: GrantsDep, body: ShiftCorrectIn):
    """A manager's correction of start/end (``reason`` required, ``row_version`` → 409 on mismatch).
    The shift's review becomes ``corrected`` and its numbers ``manager_adjusted``."""
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:update"), shift)
    shift = await shifts.correct_shift(db, ref, body, actor=user)
    jobs.enqueue(jobs.COMPUTE_METRICS, shift.id)
    return ResponseModel(data=await cards.shift_detail(db, shift), msg="Shift corrected")


@router.post("/shifts/{ref}/review", response_model=ResponseModel[ShiftOut])
async def review_shift(ref: str, user: Perm("fieldops.shift:approve", target=shift_target), db: DBSession,
                       grants: GrantsDep, body: ReviewIn):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:approve"), shift)
    shift = await shifts.review_shift(db, ref, decision=body.decision, note=body.note, actor=user)
    return ResponseModel(data=await cards.shift_detail(db, shift), msg=f"Shift {shift.review_status}")


@router.delete("/shifts/{ref}", response_model=ResponseModel[None])
async def delete_shift(ref: str, user: Perm("fieldops.shift:delete", target=shift_target), db: DBSession,
                       grants: GrantsDep, reason: str = Query(..., min_length=3, max_length=500)):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:delete"), shift)
    await shifts.delete_shift(db, ref, reason=reason, actor=user)
    return ResponseModel(data=None, msg="Shift deleted")


# ── scheduling: shifts, their plan, their stops ────────────────────────────────

async def _target_user(db, grants, actor, user_id: int, code: str):
    from sqlalchemy import select

    from app.modules.users.model import User

    target = await db.scalar(select(User).where(User.id == user_id))
    scope = await _visible(db, grants, actor, code)
    if target is None or not scope.allows_user(target.id, target.organization_id):
        raise FieldOpsNotFound(f"User {user_id} not found")
    return target


@router.post("/shifts", response_model=ResponseModel[ShiftOut], status_code=201)
async def schedule_shift(user: Perm("fieldops.shift:create"), db: DBSession, grants: GrantsDep,
                         body: ShiftScheduleIn):
    """Schedule a shift for a user (status ``scheduled``; the user starts it by its uuid). A ``template``
    fills what the body omits. ``start``/``end``: ``{mode: anywhere | hub | assigned_hub | place, …}`` with
    optional ``enforcement`` (geofencing) and ``radius_m``. 409 ``shift_overlaps``."""
    target = await _target_user(db, grants, user, body.user_id, "fieldops.shift:create")
    shift, created = await shifts.schedule_shift(db, body, target=target, actor=user)
    return ResponseModel(data=await cards.shift_detail(db, shift),
                         msg="Shift scheduled" if created else "Shift already scheduled")


@router.post("/shifts/bulk", response_model=ResponseModel[list[ShiftSlim]], status_code=201)
async def schedule_shifts(user: Perm("fieldops.shift:create"), db: DBSession, grants: GrantsDep,
                          body: ShiftScheduleBulkIn):
    """Schedule up to 200 shifts, all-or-nothing (one refusal rolls the whole request back)."""
    out = []
    for item in body.shifts:
        target = await _target_user(db, grants, user, item.user_id, "fieldops.shift:create")
        shift, _ = await shifts.schedule_shift(db, item, target=target, actor=user)
        out.append(shift)
    return ResponseModel(data=await cards.shift_cards(db, out), msg=f"{len(out)} shifts scheduled")


@router.patch("/shifts/{ref}/plan", response_model=ResponseModel[ShiftOut])
async def reschedule_shift(ref: str, user: Perm("fieldops.shift:update", target=shift_target), db: DBSession,
                           grants: GrantsDep, body: ShiftScheduleUpdate):
    """Edit a SCHEDULED shift's plan (window, title, work type, start/end). ``row_version`` required."""
    scope = await _visible(db, grants, user, "fieldops.shift:update")
    _ensure_visible(scope, await shifts.get_shift(db, ref))
    shift = await shifts.update_scheduled(db, ref, body, actor=user)
    return ResponseModel(data=await cards.shift_detail(db, shift), msg="Shift rescheduled")


@router.post("/shifts/{ref}/cancel", response_model=ResponseModel[ShiftOut])
async def cancel_scheduled_shift(ref: str, user: Perm("fieldops.shift:update", target=shift_target), db: DBSession,
                                 grants: GrantsDep, reason: str = Query(..., min_length=3, max_length=500)):
    """Cancel a SCHEDULED shift (and its planned stops)."""
    scope = await _visible(db, grants, user, "fieldops.shift:update")
    _ensure_visible(scope, await shifts.get_shift(db, ref))
    shift = await shifts.cancel_scheduled(db, ref, reason=reason, actor=user)
    return ResponseModel(data=await cards.shift_detail(db, shift), msg="Shift cancelled")


@router.post("/shifts/{ref}/stops", response_model=ResponseModel[list[VisitSlim]], status_code=201)
async def plan_stops(ref: str, user: Perm("fieldops.visit:create", target=shift_target), db: DBSession,
                     grants: GrantsDep, body: StopsIn):
    """Add stops (PLANNED visits, in order) to a scheduled or open shift. The rep starts each with
    ``POST /api/me/visits/{uuid}/start``."""
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.visit:create"), shift)
    rows = await visits.plan_stops(db, shift, body, actor=user)
    return ResponseModel(data=[VisitSlim.model_validate(r) for r in rows], msg=f"{len(rows)} stops planned")


# ── shift templates ─────────────────────────────────────────────────────────────

async def _template_out(db, row) -> ShiftTemplateOut:
    from app.modules.fieldops.endpoints import SIDES, EndpointValue

    ctx_hubs = await cards.hubs_by_id(db, {getattr(row, f"{s}_hub_id") for s in SIDES if getattr(row, f"{s}_hub_id")})
    place_ids = {getattr(row, f"{s}_place_id") for s in SIDES if getattr(row, f"{s}_place_id")}
    place_ids |= {h["place_id"] for h in ctx_hubs.values() if h["place_id"]}
    places = await cards.places_with_fences(db, place_ids)
    out = ShiftTemplateOut.model_validate(row)
    return out.model_copy(update={
        f"{side}_location": cards.endpoint_out(EndpointValue.of(row, side), hubs=ctx_hubs, places=places,
                                               default_radius=cards.DEFAULT_RADIUS_M)
        for side in SIDES})


@router.get("/shift-templates", response_model=ResponseModel[list[ShiftTemplateOut]])
async def list_shift_templates(_: Perm("fieldops.shift_template:read"), db: DBSession, status: str | None = None):
    rows = await templates.list_templates(db, status=status)
    return ResponseModel(data=[await _template_out(db, r) for r in rows])


@router.get("/shift-templates/{ref}", response_model=ResponseModel[ShiftTemplateOut])
async def get_shift_template(ref: str, _: Perm("fieldops.shift_template:read", target=template_target),
                             db: DBSession):
    return ResponseModel(data=await _template_out(db, await templates.get_template(db, ref)))


@router.post("/shift-templates", response_model=ResponseModel[ShiftTemplateOut], status_code=201)
async def create_shift_template(user: Perm("fieldops.shift_template:create"), db: DBSession, body: ShiftTemplateIn):
    """A template of the request's organization (usable by its subtree). Who gets it is the policy setting
    ``shift.template`` (a layer: organization-wide, per role, team, hub, user)."""
    row = await templates.create_template(db, body, actor=user)
    return ResponseModel(data=await _template_out(db, row), msg="Shift template created")


@router.patch("/shift-templates/{ref}", response_model=ResponseModel[ShiftTemplateOut])
async def update_shift_template(ref: str, user: Perm("fieldops.shift_template:update", target=template_target),
                                db: DBSession, body: ShiftTemplateUpdate):
    """Edit a template — e.g. pin where it starts with geofencing:
    ``{"row_version": 1, "start": {"mode": "hub", "hub_id": 3, "enforcement": "soft_block"}}``. Shifts already
    started keep the values they copied."""
    row = await templates.update_template(db, ref, body, actor=user)
    return ResponseModel(data=await _template_out(db, row), msg="Shift template updated")


@router.delete("/shift-templates/{ref}", response_model=ResponseModel[None])
async def delete_shift_template(ref: str, user: Perm("fieldops.shift_template:delete", target=template_target),
                                db: DBSession, reason: str = Query(..., min_length=3, max_length=500)):
    await templates.delete_template(db, ref, reason=reason, actor=user)
    return ResponseModel(data=None, msg="Shift template deleted")


@router.get("/shift-templates/{ref}/preview", response_model=ResponseModel[dict])
async def preview_shift_template(ref: str, user: Perm("fieldops.shift_template:read", target=template_target),
                                 db: DBSession, at: dt.datetime | None = None):
    """The occurrence that applies at ``at`` (default now) and the next ones, in the template's timezone."""
    row = await templates.get_template(db, ref)
    return ResponseModel(data=await templates.preview(db, row, user=user, at=at or dt.datetime.now(dt.UTC)))


# ── visits ──────────────────────────────────────────────────────────────────────

@router.get("/visits", response_model=ResponseModel[PageModel[VisitSlim]])
async def list_visits(
    user: Perm("fieldops.visit:read"), db: DBSession, grants: GrantsDep,
    user_id: int | None = None, status: str | None = None, channel: str | None = None,
    review_status: str | None = None, account_type: str | None = None, account_id: int | None = None,
    started_from: dt.datetime | None = None, started_to: dt.datetime | None = None,
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
):
    scope = await _visible(db, grants, user, "fieldops.visit:read")
    rows = await crud.list_visits(db, visible=scope, user_id=user_id, status=status, channel=channel,
                                  review_status=review_status, account_type=account_type, account_id=account_id,
                                  date_from=started_from, date_to=started_to, limit=limit, offset=offset)
    return ResponseModel(data=_page([VisitSlim.model_validate(r) for r in rows], limit, offset))


@router.get("/visits/{ref}", response_model=ResponseModel[VisitDetailOut])
async def get_visit(ref: str, user: Perm("fieldops.visit:read", target=visit_target), db: DBSession,
                    grants: GrantsDep):
    visit = await visits.get_visit(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.visit:read"), visit)
    return ResponseModel(data=VisitDetailOut(
        visit=VisitOut.model_validate(visit),
        tasks=[TaskOut.model_validate(t) for t in await crud.tasks_of(db, visit.id)],
        participants=[ParticipantOut.model_validate(p) for p in await crud.participants_of(db, visit.id)],
        checks=[LocationCheckOut.model_validate(c) for c in await crud.checks_of(db, "visit", visit.id)],
    ))


@router.patch("/visits/{ref}", response_model=ResponseModel[VisitOut])
async def correct_visit(ref: str, user: Perm("fieldops.visit:update", target=visit_target), db: DBSession,
                        grants: GrantsDep, body: VisitCorrectIn):
    visit = await visits.get_visit(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.visit:update"), visit)
    visit = await visits.correct_visit(db, ref, body, actor=user)
    if visit.shift_id:
        jobs.enqueue(jobs.COMPUTE_METRICS, visit.shift_id)
    return ResponseModel(data=VisitOut.model_validate(visit), msg="Visit corrected")


@router.post("/visits/{ref}/review", response_model=ResponseModel[VisitOut])
async def review_visit(ref: str, user: Perm("fieldops.visit:approve", target=visit_target), db: DBSession,
                       grants: GrantsDep, body: ReviewIn):
    visit = await visits.get_visit(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.visit:approve"), visit)
    visit = await visits.review_visit(db, ref, decision=body.decision, note=body.note, actor=user)
    return ResponseModel(data=VisitOut.model_validate(visit), msg=f"Visit {visit.review_status}")


@router.post("/visits/{ref}/cancel", response_model=ResponseModel[VisitOut])
async def cancel_visit(ref: str, user: Perm("fieldops.visit:update", target=visit_target), db: DBSession,
                       grants: GrantsDep, note: str | None = Query(None, max_length=1000)):
    """Cancel a colleague's stuck visit (e.g. the app died mid-visit)."""
    visit = await visits.get_visit(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.visit:update"), visit)
    visit = await visits.cancel_as_manager(db, ref, note=note, actor=user)
    return ResponseModel(data=VisitOut.model_validate(visit), msg="Visit cancelled")


# ── live map, anomalies, review queue ──────────────────────────────────────────

@router.get("/live", response_model=ResponseModel[list[LiveUserOut]])
async def live_map(user: Perm("users.location:read"), db: DBSession, grants: GrantsDep,
                   on_shift_only: bool = True):
    scope = await _visible(db, grants, user, "users.location:read")
    rows = await crud.live(db, scope, tenant_id=user.tenant_id, on_shift_only=on_shift_only)
    return ResponseModel(data=[LiveUserOut(user_id=r.user_id, latitude=r.lat, longitude=r.lng,
                                           accuracy_m=r.accuracy_m, recorded_at=r.recorded_at,
                                           shift_uuid=r.shift_uuid, shift_status=r.shift_status,
                                           visit_uuid=r.visit_uuid) for r in rows])


@router.get("/anomalies", response_model=ResponseModel[PageModel[AnomalyOut]])
async def list_anomalies(
    user: Perm("fieldops.anomaly:read"), db: DBSession, grants: GrantsDep,
    status: str | None = "open", anomaly_type: str | None = None, severity: str | None = None,
    shift_id: int | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
):
    scope = await _visible(db, grants, user, "fieldops.anomaly:read")
    rows = await crud.list_anomalies(db, visible=scope, status=status, anomaly_type=anomaly_type,
                                     severity=severity, shift_id=shift_id, limit=limit, offset=offset)
    return ResponseModel(data=_page([AnomalyOut.model_validate(r) for r in rows], limit, offset))


@router.post("/anomalies/{ref}/resolve", response_model=ResponseModel[AnomalyOut])
async def resolve_anomaly(ref: str, user: Perm("fieldops.anomaly:approve", target=anomaly_target), db: DBSession,
                          grants: GrantsDep, body: AnomalyResolveIn):
    row = await anomalies.get_anomaly(db, ref)
    if row.user_id is not None:
        _ensure_visible(await _visible(db, grants, user, "fieldops.anomaly:approve"), row)
    row = await anomalies.resolve(db, ref, status=body.status, resolution_code=body.resolution_code,
                                  note=body.note, actor_id=user.id)
    return ResponseModel(data=AnomalyOut.model_validate(row))


@router.get("/review-queue", response_model=ResponseModel[ReviewQueueOut])
async def review_queue(user: Perm("fieldops.shift:approve"), db: DBSession, grants: GrantsDep,
                       limit: int = Query(100, ge=1, le=500)):
    """Shifts and visits awaiting review, plus open anomalies — what a manager clears each day."""
    scope = await _visible(db, grants, user, "fieldops.shift:approve")
    pending_shifts, pending_visits, open_anomalies = await crud.review_queue(db, scope, limit=limit)
    return ResponseModel(data=ReviewQueueOut(
        shifts=await cards.shift_cards(db, pending_shifts),
        visits=[VisitSlim.model_validate(v) for v in pending_visits],
        anomalies=[AnomalyOut.model_validate(a) for a in open_anomalies],
    ))


# ── policy layers (docs/fieldops/policy-layers.md) ─────────────────────────────

@router.get("/policy-settings", response_model=ResponseModel[list[dict]])
async def policy_settings(_: Perm("fieldops.policy:read")):
    """The settings catalogue: every key a layer can set, its JSON schema, default, binding (frozen /
    live / login), audience (server / client / both) and the scopes it may be set at."""
    from app.modules.fieldops.policy.settings import catalogue

    return ResponseModel(data=catalogue())


@router.get("/policy-layers", response_model=ResponseModel[list[PolicyLayerOut]])
async def list_policy_layers(_: Perm("fieldops.policy:read"), db: DBSession, scope_type: str | None = None,
                             scope_id: int | None = None, organization_id: int | None = None):
    rows = await policy.list_layers(db, scope_type=scope_type, scope_id=scope_id, organization_id=organization_id)
    return ResponseModel(data=[PolicyLayerOut.model_validate(r) for r in rows])


@router.get("/policy-layers/{ref}", response_model=ResponseModel[PolicyLayerOut])
async def get_policy_layer(ref: str, _: Perm("fieldops.policy:read", target=policy_target), db: DBSession):
    return ResponseModel(data=PolicyLayerOut.model_validate(await policy.get_layer(db, ref)))


@router.post("/policy-layers", response_model=ResponseModel[PolicyLayerWriteOut], status_code=201)
async def create_policy_layer(user: Perm("fieldops.policy:create"), db: DBSession, body: PolicyLayerIn):
    """A layer of the request's organization (``X-Organization-Code``): ``scope_type = organization`` is that
    organization's fallback for its whole subtree; role / team / hub / user layers target within it.
    422 ``invalid_policy_settings`` / ``policy_setting_locked`` / ``scope_target_not_found``;
    409 ``policy_layer_exists``."""
    layer, warnings = await policy.create_layer(db, body, actor=user)
    return ResponseModel(data=PolicyLayerWriteOut(layer=PolicyLayerOut.model_validate(layer), warnings=warnings),
                         msg="Policy layer created")


@router.patch("/policy-layers/{ref}", response_model=ResponseModel[PolicyLayerWriteOut])
async def update_policy_layer(ref: str, user: Perm("fieldops.policy:update", target=policy_target), db: DBSession,
                              body: PolicyLayerUpdate):
    """``settings`` sets/replaces the given keys (a group's fields merge); ``unset`` removes keys or
    ``key.field``s so they inherit again."""
    layer, warnings = await policy.update_layer(db, ref, body, actor=user)
    return ResponseModel(data=PolicyLayerWriteOut(layer=PolicyLayerOut.model_validate(layer), warnings=warnings),
                         msg="Policy layer updated")


@router.delete("/policy-layers/{ref}", response_model=ResponseModel[None])
async def delete_policy_layer(ref: str, user: Perm("fieldops.policy:delete", target=policy_target), db: DBSession,
                              reason: str = Query(..., min_length=3, max_length=500)):
    await policy.delete_layer(db, ref, reason=reason, actor=user)
    return ResponseModel(data=None, msg="Policy layer deleted")


@router.get("/policies/resolve", response_model=ResponseModel[dict])
async def explain_policy(user: Perm("fieldops.policy:read"), db: DBSession, grants: GrantsDep, user_id: int,
                         shift: str | None = Query(None, description="Shift uuid: resolve with its hub/beat"),
                         at: dt.datetime | None = None):
    """Explain: every resolved value, which layer set it (provenance), skipped contributions (conflicts:
    locked / scope_not_allowed / invalid_combination) and the layers applied, general → specific."""
    from sqlalchemy import select

    from app.modules.users.model import User

    scope = await _visible(db, grants, user, "fieldops.policy:read")
    target = await db.scalar(select(User).where(User.id == user_id))
    if target is None or not scope.allows_user(target.id, target.organization_id):
        raise FieldOpsNotFound("User not found")
    shift_row = await shifts.get_shift(db, shift) if shift else None
    return ResponseModel(data=await policy.explain(db, target, shift=shift_row, at=at))


@router.post("/policies/preview", response_model=ResponseModel[dict])
async def preview_policy(user: Perm("fieldops.policy:read"), db: DBSession, body: PolicyPreviewIn):
    """Dry run of a draft layer (optionally replacing ``replaces``): which users' values would change."""
    return ResponseModel(data=await policy.preview(db, body, actor=user, replace_ref=body.replaces))


__all__ = ["router"]
