"""Shifts: start, pause, resume, end, auto-close, supersede, manager correction and review.

Invariants this module keeps (the database backs each one):

* at most one OPEN (active | paused) shift per user          ``uq_shifts_one_open``
* at most one open pause per shift                          ``uq_shift_pauses_one_open``
* ``status = 'paused'`` exactly when ``paused_since`` is set ``chk_shifts_paused_since``
* no visit starts on a paused shift; no pause while a visit is in progress (service rules)
* closing a shift closes its open pause and cancels its in-progress visits — in the same
  transaction, so nothing is ever left dangling to block tomorrow's start
* every status change goes through ``transitions.transition`` (history in the same transaction)
* the system never invents a number: anything estimated is ``duration_basis =
  system_estimated``, ``review_status = pending``, and raises an anomaly

Business times are ``occurred_at`` (clock.py) — an offline start at 09:02 synced at 18:40
starts at 09:02.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.recorder import record_activity
from app.modules.fieldops import clock
from app.modules.fieldops.endpoints import SIDES, EndpointValue
from app.modules.fieldops.enums import (
    AnomalyType,
    CheckPhase,
    CheckpointLabel,
    CheckResult,
    EndpointMode,
    Enforcement,
    JustificationCode,
    ShiftSource,
    ShiftWorkType,
    DurationBasis,
    EndedBy,
    PauseEndReason,
    ReviewStatus,
    Severity,
    ShiftEndReason,
    ShiftStatus,
    SubjectType,
    TimeBasis,
    TransitionAxis,
    TransitionSource,
    VisitCancellationReason,
    VisitStatus,
)
from app.modules.fieldops.errors import (
    FieldOpsConflict,
    FieldOpsNotFound,
    FieldOpsRuleError,
)
from app.modules.fieldops.model import Shift, ShiftPause, Visit
from app.modules.fieldops.schema import (
    ShiftCorrectIn,
    ShiftEndIn,
    ShiftPauseIn,
    ShiftResumeIn,
    ShiftStartIn,
)
from app.modules.fieldops.policy.settings import MockLocationAction
from app.modules.fieldops.service import anomalies, ingest, templates, verify
from app.modules.fieldops.service.common import (
    by_ref,
    has_location_consent,
    in_progress_visit_of,
    media_exists,
    open_shift_of,
    org_timezone,
    own_shift,
    shift_brief,
    visit_brief,
)
from app.modules.fieldops.service.context import Act
from app.modules.fieldops.service.policy import EffectivePolicy, resolve_policy
from app.modules.fieldops.endpoints import from_input
from app.modules.fieldops.service.transitions import record, transition
from app.modules.hubs.assignments import hub_for

logger = structlog.get_logger("app.fieldops.shifts")

#: A shift that ends within this of its start with no activity is a ghost (app killed after start).
GHOST_MINUTES = 5


def _minutes(delta: dt.timedelta) -> Decimal:
    return Decimal(str(round(delta.total_seconds() / 60, 2)))


def policy_of(shift: Shift) -> EffectivePolicy:
    return EffectivePolicy.from_snapshot(shift.policy_snapshot)


def _require_location(body: Any, policy: EffectivePolicy) -> None:
    if body.fix is not None:
        return
    if body.manual_location is None:
        raise FieldOpsRuleError("location_required",
                                "A location fix is required; with no GPS send manual_location with a reason")
    if not policy.allow_manual_location:
        raise FieldOpsRuleError("manual_location_not_allowed", "Your work policy does not allow manual locations")


# ── start ───────────────────────────────────────────────────────────────────────

#: Received this long after it happened = decided offline; enforcement cannot block it (as for visits).
OFFLINE_AFTER = dt.timedelta(minutes=2)
#: A scheduled shift never started is ``missed`` this long after its planned end.
MISSED_AFTER = dt.timedelta(minutes=60)


async def next_shift_code(db: AsyncSession, tenant_id: int, day: dt.date) -> str:
    """``SH-YYYYMMDD-NNNN``, per tenant and business day. A transaction-scoped advisory lock serialises
    the count, so two concurrent starts cannot mint the same code (uq_shifts_code_live backs it)."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('fieldops.shift_code'), hashtext(:k))"),
                     {"k": f"{tenant_id}:{day.isoformat()}"})
    used = await db.scalar(text("SELECT count(*) FROM fieldops.shifts WHERE tenant_id = :t AND shift_code LIKE :p"),
                           {"t": tenant_id, "p": f"SH-{day:%Y%m%d}-%"})
    return f"SH-{day:%Y%m%d}-{int(used or 0) + 1:04d}"


async def resolve_endpoints(db: AsyncSession, shift: Shift) -> list[str]:
    """Freeze the shift's endpoints: ``assigned_hub`` → the hub of ``shift.hub_id`` (or ``anywhere`` when
    the user has no hub that day — returned, for the ``no_hub_assigned`` anomaly); a hub gets its place."""
    unresolved = []
    for side in SIDES:
        value = EndpointValue.of(shift, side)
        hub_id = value.hub_id
        if value.mode == EndpointMode.ASSIGNED_HUB.value:
            if shift.hub_id is None:
                unresolved.append(side)
                EndpointValue().apply(shift, side)
                continue
            hub_id = shift.hub_id
        if value.mode in (EndpointMode.ASSIGNED_HUB.value, EndpointMode.HUB.value):
            place_id = await db.scalar(text("SELECT place_id FROM hubs WHERE id = :id"), {"id": hub_id})
            EndpointValue(EndpointMode.HUB.value, hub_id, place_id, value.enforcement, value.radius_m).apply(shift, side)
    return unresolved


def cap_of(shift: Shift, policy: EffectivePolicy) -> dt.datetime:
    """When auto-close ends ``shift``: ``min(planned end + overtime, start + max hours) + grace``. Both
    bounds hold — a plan can shorten a shift, never stretch it past the policy's maximum."""
    if shift.auto_close_at is not None:
        return shift.auto_close_at
    return compute_auto_close(shift, policy)


def compute_auto_close(shift: Shift, policy: EffectivePolicy) -> dt.datetime:
    cap = shift.started_at + dt.timedelta(hours=policy.number("max_shift_hours"))
    if shift.planned_end_at is not None:
        cap = min(cap, shift.planned_end_at + dt.timedelta(minutes=int(policy.overtime_minutes)))
    return cap + dt.timedelta(minutes=int(policy.auto_close_grace_minutes))


async def _scheduled_now(db: AsyncSession, user_id: int, at: dt.datetime, early: dt.timedelta) -> Shift | None:
    return await db.scalar(select(Shift).where(
        Shift.user_id == user_id, Shift.status == ShiftStatus.SCHEDULED.value,
        Shift.planned_start_at - early <= at, Shift.planned_end_at > at,
    ).order_by(Shift.planned_start_at).limit(1))


async def start_shift(db: AsyncSession, act: Act, body: ShiftStartIn, *, device_id: int | None) -> tuple[Shift, bool]:
    """Open a shift. Returns (shift, created); a replay of the same uuid returns the existing shift.

    The plan comes from, in order: the SCHEDULED shift whose uuid this is (adopted) → refused if another
    scheduled shift covers now (start that one) → the user's shift TEMPLATE occurrence → ad hoc when the
    policy allows it. Runs in a SAVEPOINT: a start refused by enforcement (after its checkpoint was
    written as evidence) leaves nothing behind."""
    async with db.begin_nested():
        return await _start_shift(db, act, body, device_id=device_id)


async def _start_shift(db: AsyncSession, act: Act, body: ShiftStartIn, *, device_id: int | None) -> tuple[Shift, bool]:
    user = act.user
    when = act.when(body.occurred)
    existing = await db.scalar(select(Shift).where(Shift.uuid == body.uuid).execution_options(include_deleted=True))
    if existing is not None:
        if existing.user_id != user.id:
            raise FieldOpsConflict("uuid_conflict", "This shift uuid is already used")
        if existing.status != ShiftStatus.SCHEDULED.value or existing.deleted_at is not None:
            return existing, False                                    # a replay
    tz = await org_timezone(db, user.organization_id)
    base_policy = await resolve_policy(db, user, at=when.occurred_at)
    template = None
    if existing is None:
        scheduled = await _scheduled_now(db, user.id, when.occurred_at,
                                         dt.timedelta(minutes=int(base_policy.start_early_minutes)))
        if scheduled is not None:
            raise FieldOpsConflict("scheduled_shift_exists", "You have a scheduled shift now; start that one",
                                   data={"shift_uuid": str(scheduled.uuid), "title": scheduled.title,
                                         "planned_start_at": scheduled.planned_start_at.isoformat()})
        template = await templates.by_code(db, base_policy.shift_template)
        occ = templates.occurrence(template, when.occurred_at, tz) if template is not None else None
        if occ is None and not base_policy.allow_unscheduled_shifts:
            raise FieldOpsConflict("no_shift_available", "You have no scheduled shift and no shift template now",
                                   data={"template": template.code if template else None})
    else:
        occ = None
        if existing.planned_end_at is not None and when.occurred_at >= existing.planned_end_at:
            raise FieldOpsConflict("shift_window_closed", "This scheduled shift's window is over",
                                   data={"planned_end_at": existing.planned_end_at.isoformat()})
        # Early on the SAME business day is fine (anomaly early_start); a shift planned for a LATER day
        # cannot be started today — that would consume tomorrow's plan.
        if clock.business_date(when.occurred_at, tz) < existing.shift_date:
            raise FieldOpsConflict("shift_not_yet_startable", "This shift is scheduled for a later day",
                                   data={"shift_date": existing.shift_date.isoformat(),
                                         "planned_start_at": existing.planned_start_at.isoformat()
                                         if existing.planned_start_at else None})

    shift_date = clock.business_date(when.occurred_at, tz)
    if existing is not None:
        shift = existing
    else:
        shift = Shift(uuid=body.uuid, user_id=user.id, organization_id=user.organization_id,
                      shift_date=shift_date, source=ShiftSource.AD_HOC.value, status=ShiftStatus.ACTIVE.value,
                      planned_end_at=body.planned_end_at)
        if occ is not None:
            shift.source = ShiftSource.TEMPLATE.value
            for key, value in templates.materialize(template, occ).items():
                setattr(shift, key, value)
            shift_date = occ.day
            shift.shift_date = occ.day
    if shift.hub_id is None:
        shift.hub_id = await hub_for(db, tenant_id=user.tenant_id, user_id=user.id, day=shift_date)
    policy = await resolve_policy(db, user, shift=shift, at=when.occurred_at)

    if policy.require_location_consent and not await has_location_consent(db, user.id):
        raise FieldOpsRuleError(
            "location_consent_required",
            "Location tracking needs your consent before a shift can start (DPDP Act 2023)",
            data={"consent_type": "location_tracking", "consent_endpoint": "/api/me/consents"},
        )
    _require_location(body, policy)
    if policy.require_start_selfie and body.selfie_media_uuid is None:
        raise FieldOpsRuleError("selfie_required", "Your work policy requires a selfie to start a shift")
    if body.selfie_media_uuid is not None and not await media_exists(db, body.selfie_media_uuid, user.tenant_id):
        raise FieldOpsRuleError("selfie_not_found", "The selfie image was not found; upload it first")
    if policy.require_odometer and body.odometer_start_km is None:
        raise FieldOpsRuleError("odometer_required", "Your work policy requires the odometer reading")
    await _mock_gate(db, policy, body.fix, act=act, shift=None)

    current = await open_shift_of(db, user.id)
    if current is not None:
        await _supersede_or_refuse(db, act, current, when.occurred_at, device_id=device_id, policy=policy)

    adopting = existing is not None
    shift.device_id = device_id
    shift.policy_id = policy.policy_id
    shift.policy_snapshot = policy.snapshot()
    shift.review_status = shift.review_status or ReviewStatus.NOT_REQUIRED.value
    shift.started_at = when.occurred_at
    shift.start_received_at = act.send.received_at
    shift.start_time_basis = when.basis
    shift.start_client_timestamp = body.occurred.client_timestamp
    shift.start_manual_location_reason = body.manual_location.reason if body.fix is None else None
    shift.start_selfie_media_uuid = body.selfie_media_uuid
    shift.vehicle_id = body.vehicle_id if body.vehicle_id is not None else shift.vehicle_id
    shift.travel_mode = body.travel_mode.value if body.travel_mode else shift.travel_mode
    shift.odometer_start_km = body.odometer_start_km
    shift.notes = body.notes or shift.notes
    shift.last_activity_at = when.occurred_at
    if body.planned_end_at is not None and shift.source == ShiftSource.AD_HOC.value:
        shift.planned_end_at = body.planned_end_at
    if shift.shift_code is None:
        shift.shift_code = await next_shift_code(db, user.tenant_id, shift.shift_date)
    unresolved = await resolve_endpoints(db, shift)
    if shift.start_mode == EndpointMode.ANYWHERE.value and policy.require_start_at_place_id:
        EndpointValue(EndpointMode.PLACE.value, None, int(policy.require_start_at_place_id)).apply(shift, "start")
    shift.auto_close_at = compute_auto_close(shift, policy)
    if adopting:
        transition(db, shift, subject_type=SubjectType.SHIFT, to_state=ShiftStatus.ACTIVE.value,
                   occurred_at=when.occurred_at, time_basis=when.basis, source=TransitionSource.DEVICE,
                   client_timestamp=body.occurred.client_timestamp, request_id=act.request_id,
                   idempotency_key=act.idempotency_key, reason_code="started")
        await db.flush()
    else:
        db.add(shift)
        # The open-shift check above gives the precise 409; uq_shifts_one_open backs it against a race
        # (the global handler turns that unique violation into a 409 as well).
        await db.flush()
        record(db, subject=shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.LIFECYCLE, from_state=None,
               to_state=ShiftStatus.ACTIVE.value, occurred_at=when.occurred_at, time_basis=when.basis,
               source=TransitionSource.DEVICE, client_timestamp=body.occurred.client_timestamp,
               request_id=act.request_id, idempotency_key=act.idempotency_key)

    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.SHIFT_START.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, device_id=device_id,
                                  policy=policy)
    await _check_endpoint(db, act, shift, "start", when=when, policy=policy, justification=body.justification)
    for side in unresolved:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.NO_HUB_ASSIGNED, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"no_hub_assigned:shift:{shift.id}:{side}",
            detector="shifts", evidence={"side": side, "shift_date": shift.shift_date.isoformat()})
    if body.fix is None:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.MANUAL_LOCATION, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"manual_location:shift:{shift.id}:start",
            detector="shifts", evidence={"reason": body.manual_location.reason},
        )
    await _start_window_anomalies(db, shift, policy, when.occurred_at, tz)
    if template is not None and occ is not None \
            and template.planned_minutes > policy.number("max_shift_hours") * 60:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.TEMPLATE_EXCEEDS_MAX_HOURS, severity=Severity.INFO,
            subject_type=SubjectType.SHIFT, subject=shift, user_id=user.id, shift_id=shift.id,
            dedupe_key=f"template_exceeds_max_hours:template:{template.id}:{shift.shift_date}", detector="templates",
            evidence={"template": template.code, "planned_minutes": template.planned_minutes,
                      "max_shift_hours": policy.max_shift_hours})
    await db.flush()
    await record_activity(db, action="fieldops_shift_started", actor_id=user.id, subject_type="Shift",
                          subject_id=shift.id, context={"uuid": str(shift.uuid), "time_basis": when.basis,
                                                        "source": shift.source, "code": shift.shift_code})
    logger.info("fieldops.shift_started", shift_id=shift.id, user_id=user.id, time_basis=when.basis,
                source=shift.source, template=template.code if template is not None else None)
    return shift, True


async def _start_window_anomalies(db: AsyncSession, shift: Shift, policy: EffectivePolicy, at: dt.datetime,
                                  tz: str | None) -> None:
    earliest = policy.earliest_start_local
    early = shift.planned_start_at is not None and \
        at < shift.planned_start_at - dt.timedelta(minutes=int(policy.start_early_minutes))
    if early or (earliest is not None and clock.local_time(at, tz) < earliest):
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.EARLY_START, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id, dedupe_key=f"early_start:shift:{shift.id}",
            detector="shifts", evidence={"started_local": clock.local_time(at, tz).isoformat(),
                                         "earliest": earliest.isoformat() if earliest else None,
                                         "planned_start_at": shift.planned_start_at.isoformat()
                                         if shift.planned_start_at else None})
    if shift.planned_start_at is not None and \
            at > shift.planned_start_at + dt.timedelta(minutes=int(policy.late_start_grace_minutes)):
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.LATE_START, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id, dedupe_key=f"late_start:shift:{shift.id}",
            detector="shifts", evidence={"planned_start_at": shift.planned_start_at.isoformat(),
                                         "late_minutes": round((at - shift.planned_start_at).total_seconds() / 60, 1)})


async def _check_endpoint(db: AsyncSession, act: Act, shift: Shift, side: str, *, when: Any, policy: EffectivePolicy,
                          justification: Any = None) -> None:
    """Verify the shift's start (enforced per the endpoint) or end (never blocks) against its endpoint."""
    value = EndpointValue.of(shift, side)
    if value.is_anywhere or value.place_id is None:
        setattr(shift, f"{side}_check", CheckResult.NOT_CONFIGURED.value)
        return
    phase = CheckPhase.START if side == "start" else CheckPhase.END
    offline = act.send.received_at - when.occurred_at > OFFLINE_AFTER
    enforce = side == "start" and value.enforcement is not None
    verdict = await verify.evaluate(
        db, subject=shift, subject_type=SubjectType.SHIFT, phase=phase, user_id=shift.user_id,
        at=when.occurred_at, place_id=value.place_id, channel="field", policy=policy, offline=offline,
        justified=justification is not None, enforce=enforce,
        enforcement=value.enforcement or Enforcement.ADVISORY.value, radius_m=value.radius_m, trusted=True,
    )
    decision = verdict.decision
    where = "your shift's start location" if side == "start" else "your shift's end location"
    if decision.block_code == "justification_required":
        raise FieldOpsRuleError("justification_required", f"You are outside {where}; give a reason",
                                data={"result": verdict.result.value, "distance_m": verdict.distance_m,
                                      "reason_codes": [c.value for c in JustificationCode]})
    if decision.block_code == "outside_geofence":
        raise FieldOpsRuleError("outside_geofence", f"You are outside {where}",
                                data={"result": verdict.result.value, "distance_m": verdict.distance_m,
                                      "enforcement": "hard_block"})
    setattr(shift, f"{side}_check", verdict.result.value)
    setattr(shift, f"{side}_distance_m", round(verdict.distance_m, 1) if verdict.distance_m is not None else None)
    if decision.review_pending and shift.review_status == ReviewStatus.NOT_REQUIRED.value:
        transition(db, shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.REVIEW,
                   to_state=ReviewStatus.PENDING.value, occurred_at=when.occurred_at, time_basis=when.basis,
                   source=TransitionSource.SERVER, reason_code=decision.action.value)
    anomaly = decision.anomaly
    if verdict.result is CheckResult.OUTSIDE and (anomaly is None or anomaly is AnomalyType.OUTSIDE_GEOFENCE):
        anomaly = AnomalyType.OUTSIDE_START_PLACE if side == "start" else AnomalyType.OUTSIDE_END_PLACE
    if anomaly is not None and (value.enforcement is not None or side == "start"):
        await anomalies.open_anomaly(
            db, anomaly_type=anomaly, severity=decision.severity or Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id,
            dedupe_key=f"{anomaly.value}:shift:{shift.id}:{side}", detector="verifier",
            evidence={"side": side, "result": verdict.result.value, "distance_m": verdict.distance_m,
                      "target": verdict.target.kind.value, "offline": offline,
                      "justification": justification.model_dump(mode="json") if justification else None},
        )


async def _mock_gate(db: AsyncSession, policy: EffectivePolicy, fix: Any, *, act: Act, shift: Shift | None) -> None:
    """``security.mock_location_action`` on an ACTION's fix (shift start/end, visit start/end): a mock fix is
    refused under ``reject_and_alert`` / ``end_shift`` (the stream still keeps it — ingest flags it)."""
    if fix is None or not getattr(fix, "is_mock", False):
        return
    action = str(getattr(policy.mock_location_action, "value", policy.mock_location_action))
    if action == MockLocationAction.FLAG_ONLY.value:
        return
    raise FieldOpsRuleError("mock_location_rejected", "A mock (fake) location was detected; turn off mock location apps",
                            data={"mock_location_action": action})


async def _supersede_or_refuse(db: AsyncSession, act: Act, current: Shift, occurred_at: dt.datetime, *,
                               device_id: int | None, policy: EffectivePolicy) -> None:
    """A new start while a shift is open. From the SAME device, after the open one has been idle longer
    than ``stale_shift_after_minutes``, the stale shift is closed (superseded, review pending) — an
    offline replay cannot be answered with an error nobody can act on. Otherwise: 409."""
    last = current.last_activity_at or current.started_at
    stale = dt.timedelta(minutes=int(policy.stale_shift_after_minutes))
    if device_id is not None and current.device_id == device_id and last is not None and last + stale < occurred_at:
        await close_shift(
            db, current, ended_at=last, time_basis=TimeBasis.SERVER_RECEIPT.value, received_at=act.send.received_at,
            ended_by=EndedBy.SYSTEM, end_reason=ShiftEndReason.SUPERSEDED, to_status=ShiftStatus.AUTO_CLOSED,
            source=TransitionSource.SYSTEM, duration_basis=DurationBasis.SYSTEM_ESTIMATED,
            pause_reason=PauseEndReason.AUTO_CLOSED, visit_reason=VisitCancellationReason.SUPERSEDED,
        )
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.SUPERSEDED_SHIFT, severity=Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=current, user_id=current.user_id, shift_id=current.id,
            dedupe_key=f"superseded_shift:shift:{current.id}", detector="shifts",
            evidence={"last_activity_at": last.isoformat(), "new_start_at": occurred_at.isoformat()},
        )
        return
    raise FieldOpsConflict("shift_already_active", "You already have an open shift",
                           data={"active_shift": shift_brief(current)})


# ── close (shared by end / auto-close / supersede) ────────────────────────────

async def close_shift(
    db: AsyncSession,
    shift: Shift,
    *,
    ended_at: dt.datetime,
    time_basis: str,
    received_at: dt.datetime,
    ended_by: EndedBy,
    end_reason: ShiftEndReason,
    to_status: ShiftStatus,
    source: TransitionSource,
    duration_basis: DurationBasis,
    pause_reason: PauseEndReason,
    visit_reason: VisitCancellationReason,
    client_timestamp: dt.datetime | None = None,
    act: Act | None = None,
) -> None:
    """Close ``shift`` at ``ended_at``: end its open pause, cancel its in-progress visits, compute the
    attendance numbers, transition. One transaction; nothing is left dangling."""
    ended_at = max(ended_at, shift.started_at) if shift.started_at else ended_at
    open_pause = await db.scalar(select(ShiftPause).where(ShiftPause.shift_id == shift.id,
                                                          ShiftPause.ended_at.is_(None)))
    if open_pause is not None:
        end_pause(db, open_pause, ended_at=max(ended_at, open_pause.started_at), time_basis=time_basis,
                  received_at=received_at, ended_by=ended_by, reason=pause_reason, source=source)

    stuck = (await db.scalars(select(Visit).where(Visit.shift_id == shift.id,
                                                  Visit.status == VisitStatus.IN_PROGRESS.value))).all()
    for visit in stuck:
        visit.ended_at = max(ended_at, visit.started_at)
        visit.end_received_at = received_at
        visit.end_time_basis = time_basis
        visit.cancellation_reason = visit_reason.value
        visit.cancelled_at = received_at
        visit.review_status = ReviewStatus.PENDING.value
        transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.CANCELLED.value,
                   occurred_at=visit.ended_at, time_basis=time_basis, source=source, reason_code=visit_reason.value)

    await db.flush()
    pauses = (await db.scalars(select(ShiftPause).where(ShiftPause.shift_id == shift.id))).all()
    pause_total = sum(((p.ended_at - p.started_at) for p in pauses if p.ended_at), dt.timedelta())
    unpaid = sum(((p.ended_at - p.started_at) for p in pauses if p.ended_at and not p.is_paid), dt.timedelta())
    wall = ended_at - shift.started_at if shift.started_at else dt.timedelta()

    shift.ended_at = ended_at
    shift.end_received_at = received_at
    shift.end_time_basis = time_basis
    shift.end_client_timestamp = client_timestamp
    shift.ended_by = ended_by.value
    shift.end_reason = end_reason.value
    shift.paused_since = None
    shift.pause_minutes = _minutes(pause_total)
    shift.unpaid_pause_minutes = _minutes(unpaid)
    shift.wall_clock_minutes = _minutes(wall)
    shift.paid_minutes = _minutes(max(wall - unpaid, dt.timedelta()))
    shift.duration_basis = duration_basis.value
    if duration_basis is DurationBasis.SYSTEM_ESTIMATED and shift.review_status == ReviewStatus.NOT_REQUIRED.value:
        transition(db, shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.REVIEW,
                   to_state=ReviewStatus.PENDING.value, occurred_at=ended_at, time_basis=time_basis, source=source,
                   reason_code=end_reason.value)
    transition(db, shift, subject_type=SubjectType.SHIFT, to_state=to_status.value, occurred_at=ended_at,
               time_basis=time_basis, source=source, reason_code=end_reason.value, client_timestamp=client_timestamp,
               request_id=act.request_id if act else None, idempotency_key=act.idempotency_key if act else None)
    await db.flush()


def end_pause(db: AsyncSession, pause: ShiftPause, *, ended_at: dt.datetime, time_basis: str,
              received_at: dt.datetime, ended_by: EndedBy, reason: PauseEndReason, source: TransitionSource,
              client_timestamp: dt.datetime | None = None, act: Act | None = None) -> None:
    pause.ended_at = ended_at
    pause.end_received_at = received_at
    pause.end_time_basis = time_basis
    pause.end_client_timestamp = client_timestamp
    pause.ended_by = ended_by.value
    pause.end_reason = reason.value
    record(db, subject=pause, subject_type=SubjectType.SHIFT_PAUSE, axis=TransitionAxis.LIFECYCLE,
           from_state="open", to_state=reason.value, occurred_at=ended_at, time_basis=time_basis, source=source,
           client_timestamp=client_timestamp, request_id=act.request_id if act else None,
           idempotency_key=act.idempotency_key if act else None)


# ── pause / resume ───────────────────────────────────────────────────────────────

async def pause_shift(db: AsyncSession, act: Act, shift_uuid: uuid_lib.UUID, body: ShiftPauseIn) -> ShiftPause:
    user = act.user
    shift = await own_shift(db, user, shift_uuid)
    existing = await db.scalar(select(ShiftPause).where(ShiftPause.uuid == body.uuid))
    if existing is not None:
        if existing.shift_id != shift.id:
            raise FieldOpsConflict("uuid_conflict", "This pause uuid is already used")
        return existing
    if shift.status == ShiftStatus.PAUSED.value:
        raise FieldOpsConflict("shift_already_paused", "The shift is already paused",
                               data={"paused_since": shift.paused_since.isoformat() if shift.paused_since else None})
    if shift.status != ShiftStatus.ACTIVE.value:
        raise FieldOpsConflict("shift_not_active", f"The shift is {shift.status}")
    visit = await in_progress_visit_of(db, user.id)
    if visit is not None:
        raise FieldOpsConflict("visit_in_progress", "End the visit in progress before pausing",
                               data={"active_visit": visit_brief(visit)})
    policy = policy_of(shift)
    when = act.when(body.occurred)
    started_at = max(when.occurred_at, shift.started_at)
    pause = ShiftPause(
        uuid=body.uuid, shift_id=shift.id, user_id=user.id, organization_id=shift.organization_id,
        pause_type=body.pause_type.value, reason=body.reason,
        is_paid=body.pause_type.value in (policy.paid_pause_types or []),
        tracking_suspended=not bool(policy.track_during_pause),
        started_at=started_at, start_received_at=act.send.received_at, start_time_basis=when.basis,
        start_client_timestamp=body.occurred.client_timestamp,
    )
    db.add(pause)
    await db.flush()          # status 'active' was checked above; uq_shift_pauses_one_open backs a race
    record(db, subject=pause, subject_type=SubjectType.SHIFT_PAUSE, axis=TransitionAxis.LIFECYCLE, from_state=None,
           to_state="open", occurred_at=started_at, time_basis=when.basis, source=TransitionSource.DEVICE,
           client_timestamp=body.occurred.client_timestamp, reason_code=body.pause_type.value, note=body.reason,
           request_id=act.request_id, idempotency_key=act.idempotency_key)
    shift.paused_since = started_at
    shift.pause_count = (shift.pause_count or 0) + 1
    transition(db, shift, subject_type=SubjectType.SHIFT, to_state=ShiftStatus.PAUSED.value, occurred_at=started_at,
               time_basis=when.basis, source=TransitionSource.DEVICE, reason_code=body.pause_type.value,
               client_timestamp=body.occurred.client_timestamp, request_id=act.request_id,
               idempotency_key=act.idempotency_key)
    await db.flush()
    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.SHIFT_PAUSE.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, device_id=shift.device_id,
                                  policy=policy)
    if shift.pause_count > int(policy.max_pauses_per_shift):
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.TOO_MANY_PAUSES, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"too_many_pauses:shift:{shift.id}",
            detector="shifts", evidence={"pause_count": shift.pause_count, "max": policy.max_pauses_per_shift},
        )
    await ingest.touch_shifts(db, {shift.id: started_at})
    return pause


async def resume_shift(db: AsyncSession, act: Act, shift_uuid: uuid_lib.UUID, body: ShiftResumeIn) -> ShiftPause:
    user = act.user
    shift = await own_shift(db, user, shift_uuid)
    pause = await db.scalar(select(ShiftPause).where(ShiftPause.shift_id == shift.id, ShiftPause.ended_at.is_(None)))
    if shift.status != ShiftStatus.PAUSED.value or pause is None:
        raise FieldOpsConflict("shift_not_paused", f"The shift is {shift.status}, not paused")
    policy = policy_of(shift)
    when = act.when(body.occurred)
    ended_at = max(when.occurred_at, pause.started_at)
    end_pause(db, pause, ended_at=ended_at, time_basis=when.basis, received_at=act.send.received_at,
              ended_by=EndedBy.USER, reason=PauseEndReason.RESUMED, source=TransitionSource.DEVICE,
              client_timestamp=body.occurred.client_timestamp, act=act)
    shift.paused_since = None
    if policy.pause_extends_cap and shift.auto_close_at is not None:
        shift.auto_close_at = shift.auto_close_at + (ended_at - pause.started_at)
    transition(db, shift, subject_type=SubjectType.SHIFT, to_state=ShiftStatus.ACTIVE.value, occurred_at=ended_at,
               time_basis=when.basis, source=TransitionSource.DEVICE, reason_code="resumed",
               client_timestamp=body.occurred.client_timestamp, request_id=act.request_id,
               idempotency_key=act.idempotency_key)
    await db.flush()
    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.SHIFT_RESUME.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, device_id=shift.device_id,
                                  policy=policy)
    minutes = (ended_at - pause.started_at).total_seconds() / 60
    if minutes > int(policy.max_pause_minutes):
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.LONG_PAUSE, severity=Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"long_pause:pause:{pause.id}",
            detector="shifts", evidence={"pause_uuid": str(pause.uuid), "pause_type": pause.pause_type,
                                         "minutes": round(minutes, 1), "max": policy.max_pause_minutes},
        )
    await ingest.touch_shifts(db, {shift.id: ended_at})
    return pause


# ── end ─────────────────────────────────────────────────────────────────────────

async def end_shift(db: AsyncSession, act: Act, shift_uuid: uuid_lib.UUID, body: ShiftEndIn) -> Shift:
    user = act.user
    shift = await own_shift(db, user, shift_uuid)
    if not shift.is_open:
        raise FieldOpsConflict("shift_not_active", f"The shift is already {shift.status}",
                               data={"shift": shift_brief(shift)})
    visit = await in_progress_visit_of(db, user.id)
    if visit is not None:
        raise FieldOpsConflict("visit_in_progress", "End the visit in progress before ending the shift",
                               data={"active_visit": visit_brief(visit)})
    policy = policy_of(shift)
    _require_location(body, policy)
    if policy.require_odometer and body.odometer_end_km is None:
        raise FieldOpsRuleError("odometer_required", "Your work policy requires the odometer reading")
    if body.odometer_end_km is not None and shift.odometer_start_km is not None \
            and body.odometer_end_km < shift.odometer_start_km:
        raise FieldOpsRuleError("odometer_decreased", "The end reading is below the start reading",
                                data={"odometer_start_km": str(shift.odometer_start_km)})
    when = act.when(body.occurred)
    await _mock_gate(db, policy, body.fix, act=act, shift=shift)
    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.SHIFT_END.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, device_id=shift.device_id,
                                  policy=policy)
    await _check_endpoint(db, act, shift, "end", when=when, policy=policy)
    shift.odometer_end_km = body.odometer_end_km if body.odometer_end_km is not None else shift.odometer_end_km
    if body.notes:
        shift.notes = body.notes
    await close_shift(
        db, shift, ended_at=when.occurred_at, time_basis=when.basis, received_at=act.send.received_at,
        ended_by=EndedBy.USER, end_reason=ShiftEndReason.USER, to_status=ShiftStatus.COMPLETED,
        source=TransitionSource.DEVICE, duration_basis=DurationBasis.DEVICE_REPORTED,
        pause_reason=PauseEndReason.SHIFT_ENDED, visit_reason=VisitCancellationReason.USER,
        client_timestamp=body.occurred.client_timestamp, act=act,
    )
    latest = policy.latest_end_local
    if latest is not None:
        tz = await org_timezone(db, shift.organization_id)
        if clock.local_time(shift.ended_at, tz) > latest:
            await anomalies.open_anomaly(
                db, anomaly_type=AnomalyType.LATE_END, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
                subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"late_end:shift:{shift.id}",
                detector="shifts", evidence={"latest": latest.isoformat()},
            )
    await record_activity(db, action="fieldops_shift_ended", actor_id=user.id, subject_type="Shift",
                          subject_id=shift.id, context={"uuid": str(shift.uuid), "paid_minutes": str(shift.paid_minutes)})
    return shift


# ── auto-close (system) ──────────────────────────────────────────────────────────

_DUE_SQL = text("""
    SELECT id FROM fieldops.shifts
     WHERE status IN ('active','paused') AND deleted_at IS NULL
       AND now() > COALESCE(auto_close_at,
                            COALESCE(planned_end_at, started_at
                                     + COALESCE((policy_snapshot->>'max_shift_hours')::numeric, 12) * interval '1 hour')
                            + COALESCE((policy_snapshot->>'auto_close_grace_minutes')::int, 60) * interval '1 minute')
     ORDER BY id
     LIMIT :limit
     FOR UPDATE SKIP LOCKED
""")

_MISSED_SQL = text("""
    SELECT id FROM fieldops.shifts
     WHERE status = 'scheduled' AND deleted_at IS NULL AND planned_end_at + :after < now()
     ORDER BY id
     LIMIT :limit
     FOR UPDATE SKIP LOCKED
""")

_LAST_ACTIVITY_SQL = text("""
    SELECT GREATEST(
        (SELECT max(occurred_at) FROM fieldops.location_pings
          WHERE shift_id = :id AND NOT is_mock AND (quality_flags & :untrusted) = 0),
        (SELECT max(COALESCE(ended_at, started_at)) FROM fieldops.visits WHERE shift_id = :id AND deleted_at IS NULL),
        (SELECT max(t.performed_at) FROM fieldops.visit_tasks t JOIN fieldops.visits v ON v.id = t.visit_id
          WHERE v.shift_id = :id AND t.deleted_at IS NULL),
        (SELECT max(COALESCE(ended_at, started_at)) FROM fieldops.shift_pauses WHERE shift_id = :id AND deleted_at IS NULL)
    )
""")




async def auto_close_due(db: AsyncSession, *, limit: int = 200) -> list[int]:
    """Close every open shift past its cap (planned end, else start + max hours, plus grace).

    ``effective_end = min(max(last activity, start), cap)`` — stale background pings cannot stretch a
    shift past its cap, and a shift with no activity closes AT its start (0 minutes, ghost anomaly)
    instead of becoming a false 16-hour day. Runs as ``system:fieldops-autoclose``; ``SKIP LOCKED``
    keeps two workers from closing the same shift.
    """
    from app.modules.fieldops.enums import UNTRUSTED_FLAGS

    ids = (await db.execute(_DUE_SQL, {"limit": limit})).scalars().all()
    closed = []
    now = dt.datetime.now(dt.UTC)
    for shift_id in ids:
        shift = await db.scalar(select(Shift).where(Shift.id == shift_id).execution_options(all_tenants=True))
        if shift is None or not shift.is_open:
            continue
        policy = policy_of(shift)
        last = await db.scalar(_LAST_ACTIVITY_SQL, {"id": shift.id, "untrusted": int(UNTRUSTED_FLAGS)})
        cap = cap_of(shift, policy)
        effective = min(max(last or shift.started_at, shift.started_at), cap)
        await close_shift(
            db, shift, ended_at=effective, time_basis=TimeBasis.SERVER_RECEIPT.value, received_at=now,
            ended_by=EndedBy.SYSTEM, end_reason=ShiftEndReason.AUTO_CLOSED, to_status=ShiftStatus.AUTO_CLOSED,
            source=TransitionSource.SYSTEM, duration_basis=DurationBasis.SYSTEM_ESTIMATED,
            pause_reason=PauseEndReason.AUTO_CLOSED, visit_reason=VisitCancellationReason.SHIFT_AUTO_CLOSED,
        )
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.AUTO_CLOSED, severity=Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id, dedupe_key=f"auto_closed:shift:{shift.id}",
            detector="autoclose", evidence={"last_activity_at": last.isoformat() if last else None,
                                            "cap": cap.isoformat(), "effective_end": effective.isoformat()},
        )
        if last is None or effective - shift.started_at < dt.timedelta(minutes=GHOST_MINUTES):
            await anomalies.open_anomaly(
                db, anomaly_type=AnomalyType.GHOST_SHIFT, severity=Severity.CRITICAL, subject_type=SubjectType.SHIFT,
                subject=shift, user_id=shift.user_id, shift_id=shift.id, dedupe_key=f"ghost_shift:shift:{shift.id}",
                detector="autoclose", evidence={"last_activity_at": last.isoformat() if last else None},
            )
        closed.append(shift.id)
        logger.info("fieldops.shift_auto_closed", shift_id=shift.id, user_id=shift.user_id,
                    minutes=str(shift.wall_clock_minutes), ghost=last is None)
    await db.flush()
    return closed


_SILENT_SQL = text("""
    SELECT id FROM fieldops.shifts
     WHERE status = 'active' AND deleted_at IS NULL
       AND COALESCE(last_activity_at, started_at)
           < now() - make_interval(secs => COALESCE((policy_snapshot->>'silence_factor')::float8, 3)
                                          * COALESCE((policy_snapshot->>'max_interval_s')::float8, 600))
       AND COALESCE(policy_snapshot->>'tracking_mode', 'continuous') = 'continuous'
     ORDER BY id
     LIMIT :limit
""")


async def detect_silent(db: AsyncSession, *, limit: int = 500) -> int:
    """The live zombie backstop: an ACTIVE (not paused) continuously-tracked shift with no activity for
    ``silence_factor × max_interval_s`` raises ``tracking_silent`` — once per silent stretch (the dedupe key
    carries the last activity instant, so a new silence after pings resumed is a new anomaly). It does
    not close the shift: auto-close does that at ``auto_close_at``."""
    ids = (await db.execute(_SILENT_SQL, {"limit": limit})).scalars().all()
    raised = 0
    for shift_id in ids:
        shift = await db.scalar(select(Shift).where(Shift.id == shift_id).execution_options(all_tenants=True))
        if shift is None:
            continue
        since = shift.last_activity_at or shift.started_at
        policy = policy_of(shift)
        if await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.TRACKING_SILENT, severity=Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id,
            dedupe_key=f"tracking_silent:shift:{shift.id}:{int(since.timestamp())}", detector="silence",
            evidence={"silent_since": since.isoformat(), "threshold_s": policy.number("silence_factor")
                      * policy.number("max_interval_s")},
        ):
            raised += 1
    await db.flush()
    return raised


#: A template occurrence is listed as an upcoming (virtual) shift when it starts within this.
VIRTUAL_HORIZON = dt.timedelta(hours=12)


async def virtual_entries(db: AsyncSession, user: Any) -> list:
    """Template occurrences nobody has started, for ``GET /me/shifts``: the occurrence ``now`` is in (or
    today's, before its start) and, when it starts within 12 h, the next — skipping any day the user
    already has a real (non-cancelled) shift. ``uuid`` is null: the app starts it with its own uuid."""
    from app.modules.fieldops import cards

    policy = await resolve_policy(db, user)
    template = await templates.by_code(db, policy.shift_template)
    if template is None:
        return []
    now = dt.datetime.now(dt.UTC)
    tz = await org_timezone(db, user.organization_id)
    occs = templates.next_occurrences(template, now, tz, days=2)
    if not occs:
        return []
    taken = set((await db.execute(text(
        "SELECT shift_date FROM fieldops.shifts WHERE tenant_id = :t AND user_id = :u AND deleted_at IS NULL "
        "AND status <> 'cancelled' AND shift_date = ANY(CAST(:days AS date[]))"),
        {"t": user.tenant_id, "u": user.id, "days": [o.day for o in occs]})).scalars().all())
    if await open_shift_of(db, user.id) is not None:
        return []
    out = []
    for i, occ in enumerate(occs):
        if occ.day in taken or (i > 0 and occ.planned_start_at - now > VIRTUAL_HORIZON):
            continue
        hub_id = await hub_for(db, tenant_id=user.tenant_id, user_id=user.id, day=occ.day)
        hub = (await cards.hubs_by_id(db, {hub_id})).get(hub_id) if hub_id else None
        out.append(await cards.virtual_card(db, user_id=user.id, template=template, occ=occ, hub=hub))
    return out


async def mark_missed(db: AsyncSession, *, limit: int = 200) -> list[int]:
    """Scheduled shifts whose planned end (+ ``MISSED_AFTER``) passed without a start → ``missed``
    (anomaly ``missed_shift``). Template days create no row, so they never go missed."""
    ids = (await db.execute(_MISSED_SQL, {"limit": limit, "after": MISSED_AFTER})).scalars().all()
    now = dt.datetime.now(dt.UTC)
    for shift_id in ids:
        shift = await db.scalar(select(Shift).where(Shift.id == shift_id).execution_options(all_tenants=True))
        if shift is None or shift.status != ShiftStatus.SCHEDULED.value:
            continue
        transition(db, shift, subject_type=SubjectType.SHIFT, to_state=ShiftStatus.MISSED.value, occurred_at=now,
                   time_basis=TimeBasis.SERVER_RECEIPT.value, source=TransitionSource.SYSTEM, reason_code="not_started")
        await db.flush()
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.MISSED_SHIFT, severity=Severity.WARNING, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=shift.user_id, shift_id=shift.id, dedupe_key=f"missed_shift:shift:{shift.id}",
            detector="autoclose", evidence={"planned_start_at": shift.planned_start_at.isoformat(),
                                            "planned_end_at": shift.planned_end_at.isoformat()})
        logger.info("fieldops.shift_missed", shift_id=shift.id, user_id=shift.user_id)
    await db.flush()
    return list(ids)


# ── scheduling (managers) ───────────────────────────────────────────────────────

async def _overlapping(db: AsyncSession, user_id: int, start: dt.datetime, end: dt.datetime,
                       exclude_id: int | None = None) -> Shift | None:
    stmt = select(Shift).where(Shift.user_id == user_id, Shift.status == ShiftStatus.SCHEDULED.value,
                               Shift.planned_start_at < end, Shift.planned_end_at > start)
    if exclude_id is not None:
        stmt = stmt.where(Shift.id != exclude_id)
    return await db.scalar(stmt.limit(1))


async def schedule_shift(db: AsyncSession, body: Any, *, target: Any, actor: Any) -> tuple[Shift, bool]:
    """Create a SCHEDULED shift for ``target`` (the user starts it by its uuid). A template (``body.template``)
    fills what the body omits. Returns (shift, created); a replay of the same uuid returns it."""
    if body.uuid is not None:
        existing = await db.scalar(select(Shift).where(Shift.uuid == body.uuid).execution_options(include_deleted=True))
        if existing is not None:
            if existing.user_id != target.id:
                raise FieldOpsConflict("uuid_conflict", "This shift uuid is already used")
            return existing, False
    template = await templates.get_template(db, body.template) if body.template else None
    start, end = body.planned_start_at, body.planned_end_at
    tz = await org_timezone(db, target.organization_id)
    if template is not None and (start is None or end is None):
        zone = templates._zone(template.timezone or tz)
        day = body.date or (start.astimezone(zone).date() if start is not None
                            else dt.datetime.now(dt.UTC).astimezone(zone).date())
        if not templates.applies_on(template, day):
            raise FieldOpsRuleError("template_not_on_day", f"Template {template.code} does not apply on {day}",
                                    data={"date": day.isoformat()})
        start, end = templates._window(template, day, zone)
    if start is None or end is None:
        raise FieldOpsRuleError("planned_window_required", "Give planned_start_at and planned_end_at, or a template")
    if end <= start:
        raise FieldOpsRuleError("end_before_start", "planned_end_at must be after planned_start_at")
    if end - start > dt.timedelta(hours=24):
        raise FieldOpsRuleError("planned_window_too_long", "A shift cannot be planned for more than 24 hours")
    clash = await _overlapping(db, target.id, start, end)
    if clash is not None:
        raise FieldOpsConflict("shift_overlaps", "The user already has a scheduled shift in that window",
                               data={"shift_uuid": str(clash.uuid),
                                     "planned_start_at": clash.planned_start_at.isoformat(),
                                     "planned_end_at": clash.planned_end_at.isoformat()})
    day_tz = template.timezone if template is not None and template.timezone else tz
    shift_date = clock.business_date(start, day_tz)
    shift = Shift(user_id=target.id, organization_id=target.organization_id, shift_date=shift_date,
                  status=ShiftStatus.SCHEDULED.value, review_status=ReviewStatus.NOT_REQUIRED.value,
                  source=ShiftSource.SCHEDULED.value, planned_start_at=start, planned_end_at=end,
                  assigned_by=actor.id, notes=body.notes)
    if body.uuid is not None:
        shift.uuid = body.uuid
    if template is not None:
        fields = templates.materialize(template, templates.Occurrence(shift_date, start, end, day_tz or "UTC"))
        for key, value in fields.items():
            if key not in ("planned_start_at", "planned_end_at"):
                setattr(shift, key, value)
    shift.title = body.title or shift.title
    shift.work_type = body.work_type.value if body.work_type else (shift.work_type or ShiftWorkType.OTHER.value)
    for side in SIDES:
        if side in body.model_fields_set:
            (await from_input(db, getattr(body, side), tenant_id=target.tenant_id,
                              organization_id=target.organization_id)).apply(shift, side)
    shift.hub_id = await hub_for(db, tenant_id=target.tenant_id, user_id=target.id, day=shift_date)
    shift.shift_code = await next_shift_code(db, target.tenant_id, shift_date)
    if shift.hub_id is not None:
        await resolve_endpoints(db, shift)   # with no hub yet, assigned_hub stays and is re-read at start
    db.add(shift)
    await db.flush()
    record(db, subject=shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.LIFECYCLE, from_state=None,
           to_state=ShiftStatus.SCHEDULED.value, occurred_at=dt.datetime.now(dt.UTC),
           time_basis=TimeBasis.SERVER_RECEIPT.value, source=TransitionSource.MANAGER, reason_code="scheduled")
    await db.flush()
    await record_activity(db, action="fieldops_shift_scheduled", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, context={"user_id": target.id, "code": shift.shift_code,
                                                        "template": template.code if template else None})
    return shift, True


async def update_scheduled(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> Shift:
    shift = await get_shift(db, ref)
    if shift.status != ShiftStatus.SCHEDULED.value:
        raise FieldOpsConflict("shift_not_scheduled",
                               f"Only a scheduled shift's plan can be edited (it is {shift.status})")
    if shift.row_version != body.row_version:
        raise FieldOpsConflict("row_version_conflict", "The shift changed since you loaded it; reload and retry",
                               data={"current_row_version": shift.row_version})
    start = body.planned_start_at or shift.planned_start_at
    end = body.planned_end_at or shift.planned_end_at
    if end <= start:
        raise FieldOpsRuleError("end_before_start", "planned_end_at must be after planned_start_at")
    clash = await _overlapping(db, shift.user_id, start, end, exclude_id=shift.id)
    if clash is not None:
        raise FieldOpsConflict("shift_overlaps", "The user already has a scheduled shift in that window",
                               data={"shift_uuid": str(clash.uuid)})
    shift.planned_start_at, shift.planned_end_at = start, end
    for key in ("title", "notes"):
        if key in body.model_fields_set:
            setattr(shift, key, getattr(body, key))
    if body.work_type is not None:
        shift.work_type = body.work_type.value
    for side in SIDES:
        if side in body.model_fields_set:
            (await from_input(db, getattr(body, side), tenant_id=shift.tenant_id,
                              organization_id=shift.organization_id)).apply(shift, side)
    if shift.hub_id is not None:
        await resolve_endpoints(db, shift)
    await db.flush()
    await record_activity(db, action="fieldops_shift_rescheduled", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, context={"fields": sorted(body.model_fields_set - {"row_version"})})
    return shift


async def cancel_scheduled(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> Shift:
    shift = await get_shift(db, ref)
    if shift.status != ShiftStatus.SCHEDULED.value:
        raise FieldOpsConflict("shift_not_scheduled",
                               f"Only a scheduled shift can be cancelled here (it is {shift.status})")
    now = dt.datetime.now(dt.UTC)
    shift.cancellation_reason = reason
    transition(db, shift, subject_type=SubjectType.SHIFT, to_state=ShiftStatus.CANCELLED.value, occurred_at=now,
               time_basis=TimeBasis.MANAGER.value, source=TransitionSource.MANAGER, note=reason)
    planned = (await db.scalars(select(Visit).where(Visit.shift_id == shift.id,
                                                    Visit.status == VisitStatus.PLANNED.value))).all()
    for visit in planned:
        visit.cancellation_reason = VisitCancellationReason.MANAGER.value
        visit.cancelled_at = now
        transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.CANCELLED.value, occurred_at=now,
                   time_basis=TimeBasis.MANAGER.value, source=TransitionSource.MANAGER, reason_code="shift_cancelled")
    await db.flush()
    await record_activity(db, action="fieldops_shift_cancelled", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, context={"reason": reason})
    return shift


async def handover(db: AsyncSession, act: Act, shift_uuid: uuid_lib.UUID, *, device_id: int | None) -> Shift:
    """Rebind my open shift to THIS device (I signed in on a new phone): its fixes stop being
    ``foreign_device``. Recorded as a transition (with the device change) + an info anomaly."""
    shift = await own_shift(db, act.user, shift_uuid)
    if not shift.is_open:
        raise FieldOpsConflict("shift_not_active", f"The shift is {shift.status}")
    if device_id is None:
        raise FieldOpsRuleError("device_not_registered",
                                "Register this device (POST /me/devices) and send X-Device-Session first")
    if shift.device_id == device_id:
        return shift
    previous = shift.device_id
    shift.device_id = device_id
    await db.flush()
    await record_activity(db, action="fieldops_shift_device_handover", actor_id=act.user.id, subject_type="Shift",
                          subject_id=shift.id, changes={"device_id": [previous, device_id]},
                          context={"uuid": str(shift.uuid), "request_id": act.request_id})
    await anomalies.open_anomaly(
        db, anomaly_type=AnomalyType.DEVICE_HANDOVER, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
        subject=shift, user_id=shift.user_id, shift_id=shift.id,
        dedupe_key=f"device_handover:shift:{shift.id}:{device_id}", detector="shifts",
        evidence={"from_device_id": previous, "to_device_id": device_id})
    return shift


# ── manager side ────────────────────────────────────────────────────────────────

async def get_shift(db: AsyncSession, ref: str) -> Shift:
    shift = await db.scalar(select(Shift).where(by_ref(Shift, ref)))
    if shift is None:
        raise FieldOpsNotFound(f"Shift '{ref}' not found")
    return shift


async def correct_shift(db: AsyncSession, ref: str, body: ShiftCorrectIn, *, actor: Any) -> Shift:
    """A manager's correction of start/end. The before/after goes into the transition's ``changes``;
    the numbers are recomputed from the corrected times and marked ``manager_adjusted``."""
    shift = await get_shift(db, ref)
    if shift.row_version != body.row_version:
        raise FieldOpsConflict("row_version_conflict", "The shift changed since you loaded it; reload and retry",
                               data={"current_row_version": shift.row_version})
    if body.ended_at is not None and shift.is_open:
        raise FieldOpsRuleError("shift_open", "An open shift's end cannot be corrected; end it first")
    started = body.started_at or shift.started_at
    ended = body.ended_at or shift.ended_at
    if started is not None and ended is not None and ended < started:
        raise FieldOpsRuleError("end_before_start", "The end cannot be before the start")
    changes: dict[str, list] = {}
    now = dt.datetime.now(dt.UTC)
    if body.started_at is not None and body.started_at != shift.started_at:
        changes["started_at"] = [shift.started_at.isoformat() if shift.started_at else None, body.started_at.isoformat()]
        shift.started_at = body.started_at
        shift.start_time_basis = TimeBasis.MANAGER.value
        tz = await org_timezone(db, shift.organization_id)
        shift.shift_date = clock.business_date(body.started_at, tz)
    if body.ended_at is not None and body.ended_at != shift.ended_at:
        changes["ended_at"] = [shift.ended_at.isoformat() if shift.ended_at else None, body.ended_at.isoformat()]
        shift.ended_at = body.ended_at
        shift.end_time_basis = TimeBasis.MANAGER.value
    if body.notes is not None:
        shift.notes = body.notes
    if not changes and body.notes is None:
        return shift
    if shift.ended_at is not None and shift.started_at is not None:
        pauses = (await db.scalars(select(ShiftPause).where(ShiftPause.shift_id == shift.id))).all()
        unpaid = sum(((p.ended_at - p.started_at) for p in pauses if p.ended_at and not p.is_paid), dt.timedelta())
        wall = shift.ended_at - shift.started_at
        shift.wall_clock_minutes = _minutes(wall)
        shift.paid_minutes = _minutes(max(wall - unpaid, dt.timedelta()))
    if changes:
        shift.duration_basis = DurationBasis.MANAGER_ADJUSTED.value
        shift.reviewed_by = actor.id
        shift.reviewed_at = now
        transition(db, shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.REVIEW,
                   to_state=ReviewStatus.CORRECTED.value, occurred_at=now, time_basis=TimeBasis.MANAGER.value,
                   source=TransitionSource.MANAGER, note=body.reason, changes=changes)
    await db.flush()
    await record_activity(db, action="fieldops_shift_corrected", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, changes={"after": changes}, context={"reason": body.reason})
    return shift


async def review_shift(db: AsyncSession, ref: str, *, decision: str, note: str | None, actor: Any) -> Shift:
    shift = await get_shift(db, ref)
    if shift.is_open:
        raise FieldOpsRuleError("shift_open", "An open shift cannot be reviewed yet")
    to_state = ReviewStatus.APPROVED.value if decision == "approve" else ReviewStatus.REJECTED.value
    now = dt.datetime.now(dt.UTC)
    transition(db, shift, subject_type=SubjectType.SHIFT, axis=TransitionAxis.REVIEW, to_state=to_state,
               occurred_at=now, time_basis=TimeBasis.MANAGER.value, source=TransitionSource.MANAGER, note=note)
    shift.reviewed_by = actor.id
    shift.reviewed_at = now
    await db.flush()
    await record_activity(db, action=f"fieldops_shift_{to_state}", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, context={"note": note})
    return shift


async def delete_shift(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> None:
    shift = await get_shift(db, ref)
    if shift.is_open:
        raise FieldOpsRuleError("shift_open", "An open shift cannot be deleted; end or cancel it first")
    shift.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    await record_activity(db, action="fieldops_shift_deleted", actor_id=actor.id, subject_type="Shift",
                          subject_id=shift.id, context={"reason": reason})




__all__ = [
    "auto_close_due", "cancel_scheduled", "cap_of", "close_shift", "compute_auto_close", "correct_shift",
    "delete_shift", "end_pause", "end_shift", "get_shift", "handover", "mark_missed", "next_shift_code",
    "pause_shift", "policy_of", "resolve_endpoints", "resume_shift", "review_shift", "schedule_shift",
    "start_shift", "update_scheduled",
]
