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
from app.modules.fieldops.enums import (
    AnomalyType,
    CheckPhase,
    CheckpointLabel,
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
from app.modules.fieldops.service import anomalies, ingest, verify
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
from app.modules.fieldops.service.transitions import record, transition

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

async def start_shift(db: AsyncSession, act: Act, body: ShiftStartIn, *, device_id: int | None) -> tuple[Shift, bool]:
    """Open a shift. Returns (shift, created); a replay of the same uuid returns the existing shift."""
    user = act.user
    existing = await db.scalar(select(Shift).where(Shift.uuid == body.uuid).execution_options(include_deleted=True))
    if existing is not None:
        if existing.user_id != user.id:
            raise FieldOpsConflict("uuid_conflict", "This shift uuid is already used")
        return existing, False

    policy = await resolve_policy(db, user)
    if policy.require_location_consent and not await has_location_consent(db, user.id):
        raise FieldOpsRuleError(
            "location_consent_required",
            "Location tracking needs your consent before a shift can start (DPDP Act 2023)",
            data={"consent_type": "location_tracking"},
        )
    _require_location(body, policy)
    if policy.require_start_selfie and body.selfie_media_uuid is None:
        raise FieldOpsRuleError("selfie_required", "Your work policy requires a selfie to start a shift")
    if body.selfie_media_uuid is not None and not await media_exists(db, body.selfie_media_uuid, user.tenant_id):
        raise FieldOpsRuleError("selfie_not_found", "The selfie image was not found; upload it first")
    if policy.require_odometer and body.odometer_start_km is None:
        raise FieldOpsRuleError("odometer_required", "Your work policy requires the odometer reading")
    when = act.when(body.occurred)

    current = await open_shift_of(db, user.id)
    if current is not None:
        await _supersede_or_refuse(db, act, current, when.occurred_at, device_id=device_id, policy=policy)

    tz = await org_timezone(db, user.organization_id)
    shift = Shift(
        uuid=body.uuid, user_id=user.id, organization_id=user.organization_id, device_id=device_id,
        policy_id=policy.policy_id, policy_snapshot=policy.snapshot(),
        shift_date=clock.business_date(when.occurred_at, tz),
        status=ShiftStatus.ACTIVE.value, review_status=ReviewStatus.NOT_REQUIRED.value,
        planned_end_at=body.planned_end_at, started_at=when.occurred_at, start_received_at=act.send.received_at,
        start_time_basis=when.basis, start_client_timestamp=body.occurred.client_timestamp,
        start_manual_location_reason=body.manual_location.reason if body.fix is None else None,
        start_selfie_media_uuid=body.selfie_media_uuid, vehicle_id=body.vehicle_id,
        travel_mode=body.travel_mode.value if body.travel_mode else None,
        odometer_start_km=body.odometer_start_km, notes=body.notes, last_activity_at=when.occurred_at,
    )
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
    if policy.require_start_at_place_id:
        verdict = await verify.evaluate(
            db, subject=shift, subject_type=SubjectType.SHIFT, phase=CheckPhase.START, user_id=user.id,
            at=when.occurred_at, place_id=policy.require_start_at_place_id, channel="field", policy=policy,
            enforce=False,
        )
        shift.start_check = verdict.result.value
    if body.fix is None:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.MANUAL_LOCATION, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"manual_location:shift:{shift.id}:start",
            detector="shifts", evidence={"reason": body.manual_location.reason},
        )
    earliest = policy.earliest_start_local
    if earliest is not None and clock.local_time(when.occurred_at, tz) < earliest:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.EARLY_START, severity=Severity.INFO, subject_type=SubjectType.SHIFT,
            subject=shift, user_id=user.id, shift_id=shift.id, dedupe_key=f"early_start:shift:{shift.id}",
            detector="shifts", evidence={"started_local": clock.local_time(when.occurred_at, tz).isoformat(),
                                         "earliest": earliest.isoformat()},
        )
    await db.flush()
    await record_activity(db, action="fieldops_shift_started", actor_id=user.id, subject_type="Shift",
                          subject_id=shift.id, context={"uuid": str(shift.uuid), "time_basis": when.basis})
    logger.info("fieldops.shift_started", shift_id=shift.id, user_id=user.id, time_basis=when.basis)
    return shift, True


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
    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.SHIFT_END.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, device_id=shift.device_id,
                                  policy=policy)
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
       AND now() > COALESCE(planned_end_at,
                            started_at + COALESCE((policy_snapshot->>'max_shift_hours')::numeric, 12) * interval '1 hour')
                   + COALESCE((policy_snapshot->>'auto_close_grace_minutes')::int, 60) * interval '1 minute'
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


def cap_of(shift: Shift, policy: EffectivePolicy) -> dt.datetime:
    base = shift.planned_end_at or (shift.started_at + dt.timedelta(hours=policy.number("max_shift_hours")))
    return base + dt.timedelta(minutes=int(policy.auto_close_grace_minutes))


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
    "auto_close_due", "cap_of", "close_shift", "correct_shift", "delete_shift", "end_pause", "end_shift",
    "get_shift", "pause_shift", "policy_of", "resume_shift", "review_shift", "start_shift",
]
