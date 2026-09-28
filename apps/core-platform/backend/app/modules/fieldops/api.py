"""Managers' API — ``/api/fieldops/…``: shifts, visits, tracks, the live map, anomalies, the
review queue and work policies.

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
from app.modules.fieldops import crud, jobs
from app.modules.fieldops.deps import (
    anomaly_target,
    policy_target,
    shift_target,
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
    PolicyIn,
    PolicyOut,
    PolicyUpdate,
    ReviewIn,
    ReviewQueueOut,
    ShiftCorrectIn,
    ShiftDetailOut,
    ShiftOut,
    ShiftSlim,
    TaskOut,
    TrackOut,
    TrackPoint,
    VisitCorrectIn,
    VisitDetailOut,
    VisitOut,
    VisitSlim,
)
from app.modules.fieldops.scope import Visible, visible
from app.modules.fieldops.service import anomalies, metrics, policy, shifts, visits
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
    return ResponseModel(data=_page([ShiftSlim.model_validate(r) for r in rows], limit, offset))


@router.get("/shifts/{ref}", response_model=ResponseModel[ShiftDetailOut])
async def get_shift(ref: str, user: Perm("fieldops.shift:read", target=shift_target), db: DBSession,
                    grants: GrantsDep):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:read"), shift)
    stats = await crud.metrics_of(db, shift.id)
    return ResponseModel(data=ShiftDetailOut(
        shift=ShiftOut.model_validate(shift),
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
    return ResponseModel(data=ShiftOut.model_validate(shift), msg="Shift corrected")


@router.post("/shifts/{ref}/review", response_model=ResponseModel[ShiftOut])
async def review_shift(ref: str, user: Perm("fieldops.shift:approve", target=shift_target), db: DBSession,
                       grants: GrantsDep, body: ReviewIn):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:approve"), shift)
    shift = await shifts.review_shift(db, ref, decision=body.decision, note=body.note, actor=user)
    return ResponseModel(data=ShiftOut.model_validate(shift), msg=f"Shift {shift.review_status}")


@router.delete("/shifts/{ref}", response_model=ResponseModel[None])
async def delete_shift(ref: str, user: Perm("fieldops.shift:delete", target=shift_target), db: DBSession,
                       grants: GrantsDep, reason: str = Query(..., min_length=3, max_length=500)):
    shift = await shifts.get_shift(db, ref)
    _ensure_visible(await _visible(db, grants, user, "fieldops.shift:delete"), shift)
    await shifts.delete_shift(db, ref, reason=reason, actor=user)
    return ResponseModel(data=None, msg="Shift deleted")


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
        shifts=[ShiftSlim.model_validate(s) for s in pending_shifts],
        visits=[VisitSlim.model_validate(v) for v in pending_visits],
        anomalies=[AnomalyOut.model_validate(a) for a in open_anomalies],
    ))


# ── work policies ───────────────────────────────────────────────────────────────

@router.get("/policies", response_model=ResponseModel[list[PolicyOut]])
async def list_policies(_: Perm("fieldops.policy:read"), db: DBSession):
    return ResponseModel(data=[PolicyOut.model_validate(p) for p in await policy.list_policies(db)])


@router.post("/policies", response_model=ResponseModel[PolicyOut], status_code=201)
async def create_policy(_: Perm("fieldops.policy:create"), db: DBSession, body: PolicyIn):
    """A policy for the request's organization (``X-Organization-Code``), for one role or (role
    omitted) the organization default."""
    row = await policy.create_policy(db, body)
    return ResponseModel(data=PolicyOut.model_validate(row), msg="Policy created")


@router.patch("/policies/{ref}", response_model=ResponseModel[PolicyOut])
async def update_policy(ref: str, _: Perm("fieldops.policy:update", target=policy_target), db: DBSession,
                        body: PolicyUpdate):
    row = await policy.update_policy(db, ref, body)
    return ResponseModel(data=PolicyOut.model_validate(row), msg="Policy updated")


@router.delete("/policies/{ref}", response_model=ResponseModel[None])
async def delete_policy(ref: str, user: Perm("fieldops.policy:delete", target=policy_target), db: DBSession,
                        reason: str = Query(..., min_length=3, max_length=500)):
    await policy.delete_policy(db, ref, reason=reason, actor_id=user.id)
    return ResponseModel(data=None, msg="Policy deleted")


__all__ = ["router"]
