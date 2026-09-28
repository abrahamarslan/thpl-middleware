"""Visits: start (with location verification and enforcement), end, cancel, join; manager
correction and review.

Start, in order (docs/fieldops/implementation-of-shift-visits-system.md §7.4):

1. channel gate — telephonic / video need ``fieldops.telephonic_visit:create`` (the route
   passes the decision; a remote visit's checks are ``not_applicable``);
2. shift gate — ``requires_shift`` and no open shift → 422 ``shift_required``; a PAUSED shift
   → 409 ``shift_paused``;
3. the counterparty (registry-proved) and the place (explicit, else the account's primary
   linked place from the address book);
4. the ``visit_start`` checkpoint into the stream;
5. verification + enforcement (service/verify.py). A blocked start raises and the whole
   transaction — checkpoint included — rolls back; the app retries with a justification;
6. the insert — ``uq_visits_one_in_progress`` makes "two customers at once" a 409.

An OFFLINE start (received more than two minutes after it happened) is never blocked: it
already happened. It is accepted and flagged for review instead.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity.recorder import record_activity
from app.modules.fieldops.enums import (
    REMOTE_CHANNELS,
    AnomalyType,
    Channel,
    CheckPhase,
    CheckpointLabel,
    CheckResult,
    JustificationCode,
    ReviewStatus,
    Severity,
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
from app.modules.fieldops.model import Shift, Visit, VisitParticipant
from app.modules.fieldops.schema import (
    VisitCancelIn,
    VisitCorrectIn,
    VisitEndIn,
    VisitJoinIn,
    VisitStartIn,
)
from app.modules.fieldops.service import anomalies, ingest, verify
from app.modules.fieldops.service.common import (
    by_ref,
    in_progress_visit_of,
    open_shift_of,
    own_visit,
    visit_brief,
)
from app.modules.fieldops.service.context import Act
from app.modules.fieldops.service.policy import EffectivePolicy, resolve_policy
from app.modules.fieldops.service.shifts import policy_of
from app.modules.fieldops.service.transitions import record, transition

logger = structlog.get_logger("app.fieldops.visits")

#: Received this long after it happened = the device decided offline; enforcement cannot block it.
OFFLINE_AFTER = dt.timedelta(minutes=2)


async def entity_exists(db: AsyncSession, entity_type: str, entity_id: int, tenant_id: int) -> bool:
    """Prove a registry reference: the type is registered (``core.entity_types``) and the row exists in
    the type's table, in this tenant when the table is tenant-scoped."""
    target = (await db.execute(text(
        "SELECT target_schema, target_table FROM core.entity_types WHERE code = :code AND deleted_at IS NULL"
    ), {"code": entity_type})).first()
    if target is None:
        return False
    has_tenant = await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = :s AND table_name = :t "
        "AND column_name = 'tenant_id')"), {"s": target.target_schema, "t": target.target_table})
    table = f'"{target.target_schema}"."{target.target_table}"'
    where = "id = :id" + (" AND tenant_id = :tenant" if has_tenant else "")
    return bool(await db.scalar(text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {where})"),
                                {"id": entity_id, "tenant": tenant_id}))


async def registered(db: AsyncSession, entity_type: str) -> bool:
    return bool(await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM core.entity_types WHERE code = :c AND deleted_at IS NULL)"), {"c": entity_type}))


async def _account_place(db: AsyncSession, account_type: str, account_id: int, tenant_id: int) -> int | None:
    """The account's place from the address book: an open ``site`` link first, then its primary link."""
    return await db.scalar(text("""
        SELECT place_id FROM geo.place_links
         WHERE tenant_id = :tenant AND owner_type = :t AND owner_id = :i AND deleted_at IS NULL
           AND (valid_to IS NULL OR valid_to > now())
         ORDER BY (link_type = 'site') DESC, is_primary DESC, id
         LIMIT 1
    """), {"t": account_type, "i": account_id, "tenant": tenant_id})


async def _place_id(db: AsyncSession, place_uuid: uuid_lib.UUID, tenant_id: int) -> int:
    place_id = await db.scalar(text("SELECT id FROM geo.places WHERE uuid = :u AND tenant_id = :t AND deleted_at IS NULL"),
                               {"u": place_uuid, "t": tenant_id})
    if place_id is None:
        raise FieldOpsRuleError("place_not_found", f"Place {place_uuid} not found")
    return int(place_id)


async def start_visit(db: AsyncSession, act: Act, body: VisitStartIn, *, can_remote: bool,
                      device_id: int | None) -> tuple[Visit, bool]:
    """Start a visit. Returns (visit, created); a replay of the same uuid returns the existing visit.

    Runs in a SAVEPOINT: a start refused after its rows were written (enforcement blocks only once
    the checkpoint fix is in the stream as evidence) leaves nothing behind, whatever the caller's
    transaction handling."""
    async with db.begin_nested():
        return await _start_visit(db, act, body, can_remote=can_remote, device_id=device_id)


async def _start_visit(db: AsyncSession, act: Act, body: VisitStartIn, *, can_remote: bool,
                       device_id: int | None) -> tuple[Visit, bool]:
    user = act.user
    existing = await db.scalar(select(Visit).where(Visit.uuid == body.uuid).execution_options(include_deleted=True))
    if existing is not None:
        if existing.user_id != user.id:
            raise FieldOpsConflict("uuid_conflict", "This visit uuid is already used")
        return existing, False

    channel = body.channel.value
    if channel in REMOTE_CHANNELS and not can_remote:
        from app.common.exception.errors import ForbiddenError

        raise ForbiddenError("Your role may not take telephonic or video visits",
                             data={"permission": "fieldops.telephonic_visit:create"})

    # ── shift gate ──
    if body.shift_uuid is not None:
        shift = await db.scalar(select(Shift).where(Shift.uuid == body.shift_uuid, Shift.user_id == user.id))
        if shift is None:
            raise FieldOpsNotFound(f"Shift {body.shift_uuid} not found")
        if not shift.is_open:
            raise FieldOpsConflict("shift_not_active", f"The shift is {shift.status}")
    else:
        shift = await open_shift_of(db, user.id)
    policy: EffectivePolicy = policy_of(shift) if shift is not None else await resolve_policy(db, user)
    if shift is None and policy.requires_shift and not policy.allow_visits_without_shift:
        raise FieldOpsRuleError("shift_required", "Start your shift before starting a visit")
    if shift is not None and shift.status == ShiftStatus.PAUSED.value:
        raise FieldOpsConflict("shift_paused", "Resume your shift before starting a visit",
                               data={"paused_since": shift.paused_since.isoformat() if shift.paused_since else None})

    # ── counterparty and place ──
    account_type = account_id = None
    if body.account is not None:
        if not await entity_exists(db, body.account.type, body.account.id, user.tenant_id):
            raise FieldOpsRuleError("account_not_found", f"{body.account.type} {body.account.id} not found",
                                    data={"type": body.account.type, "id": body.account.id})
        account_type, account_id = body.account.type, body.account.id
    place_id = await _place_id(db, body.place_uuid, user.tenant_id) if body.place_uuid else None
    if place_id is None and account_type is not None:
        place_id = await _account_place(db, account_type, account_id, user.tenant_id)
    if channel == Channel.FIELD.value:
        if account_id is None and place_id is None:
            raise FieldOpsRuleError("visit_target_required", "A field visit needs an account or a place")
        if body.fix is None:
            if body.manual_location is None:
                raise FieldOpsRuleError("location_required",
                                        "A location fix is required; with no GPS send manual_location with a reason")
            if not policy.allow_manual_location:
                raise FieldOpsRuleError("manual_location_not_allowed",
                                        "Your work policy does not allow manual locations")

    # "Two customers at once" — checked first for a precise 409; uq_visits_one_in_progress backs it
    # against a race (the global handler turns that unique violation into a 409 too).
    running = await in_progress_visit_of(db, user.id)
    if running is not None:
        raise FieldOpsConflict("visit_in_progress", "You already have a visit in progress",
                               data={"active_visit": visit_brief(running)})

    when = act.when(body.occurred)
    offline = act.send.received_at - when.occurred_at > OFFLINE_AFTER
    visit = Visit(
        uuid=body.uuid, user_id=user.id, organization_id=user.organization_id, shift_id=shift.id if shift else None,
        device_id=device_id, channel=channel, status=VisitStatus.IN_PROGRESS.value,
        review_status=ReviewStatus.NOT_REQUIRED.value, source=body.source.value, plan_ref=body.plan_ref,
        sequence_in_plan=body.sequence_in_plan, purpose=body.purpose.value, account_type=account_type,
        account_id=account_id, place_id=place_id, planned_start_at=body.planned_start_at,
        started_at=when.occurred_at, start_received_at=act.send.received_at, start_time_basis=when.basis,
        start_client_timestamp=body.occurred.client_timestamp,
        start_check=CheckResult.NOT_APPLICABLE.value if channel in REMOTE_CHANNELS else CheckResult.NOT_CONFIGURED.value,
        end_check=CheckResult.NOT_APPLICABLE.value if channel in REMOTE_CHANNELS else CheckResult.NOT_CONFIGURED.value,
        start_justification_code=body.justification.code.value if body.justification else None,
        start_justification_note=body.justification.note if body.justification else None,
        manual_location_reason=body.manual_location.reason if body.fix is None and body.manual_location else None,
        notes=body.notes,
    )
    db.add(visit)
    await db.flush()

    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.VISIT_START.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, visit=visit,
                                  device_id=device_id, policy=policy)
    verdict = await verify.evaluate(
        db, subject=visit, subject_type=SubjectType.VISIT, phase=CheckPhase.START, user_id=user.id,
        at=when.occurred_at, place_id=place_id, channel=channel, policy=policy, offline=offline,
        justified=body.justification is not None,
    )
    decision = verdict.decision
    if decision.block_code == "justification_required":
        raise FieldOpsRuleError("justification_required", "You are outside the customer's location; give a reason",
                                data={"result": verdict.result.value, "distance_m": verdict.distance_m,
                                      "reason_codes": [c.value for c in JustificationCode]})
    if decision.block_code == "outside_geofence":
        raise FieldOpsRuleError("outside_geofence", "You are outside the customer's location",
                                data={"result": verdict.result.value, "distance_m": verdict.distance_m,
                                      "enforcement": "hard_block"})
    visit.start_check = verdict.result.value
    visit.distance_from_target_m = verdict.distance_m
    record(db, subject=visit, subject_type=SubjectType.VISIT, axis=TransitionAxis.LIFECYCLE, from_state=None,
           to_state=VisitStatus.IN_PROGRESS.value, occurred_at=when.occurred_at, time_basis=when.basis,
           source=TransitionSource.DEVICE, client_timestamp=body.occurred.client_timestamp,
           request_id=act.request_id, idempotency_key=act.idempotency_key)
    if decision.review_pending:
        transition(db, visit, subject_type=SubjectType.VISIT, axis=TransitionAxis.REVIEW,
                   to_state=ReviewStatus.PENDING.value, occurred_at=when.occurred_at, time_basis=when.basis,
                   source=TransitionSource.SERVER, reason_code=decision.action.value)
    if decision.anomaly is not None:
        await anomalies.open_anomaly(
            db, anomaly_type=decision.anomaly, severity=decision.severity, subject_type=SubjectType.VISIT,
            subject=visit, user_id=user.id, shift_id=visit.shift_id,
            dedupe_key=f"{decision.anomaly.value}:visit:{visit.id}", detector="verifier",
            evidence={"result": verdict.result.value, "distance_m": verdict.distance_m,
                      "target": verdict.target.kind.value, "offline": offline,
                      "justification": body.justification.model_dump(mode="json") if body.justification else None},
        )
    if body.fix is None and channel == Channel.FIELD.value:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.MANUAL_LOCATION, severity=Severity.INFO, subject_type=SubjectType.VISIT,
            subject=visit, user_id=user.id, shift_id=visit.shift_id, dedupe_key=f"manual_location:visit:{visit.id}",
            detector="visits", evidence={"reason": visit.manual_location_reason},
        )
    if shift is None:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.VISIT_WITHOUT_SHIFT, severity=Severity.INFO, subject_type=SubjectType.VISIT,
            subject=visit, user_id=user.id, dedupe_key=f"visit_without_shift:visit:{visit.id}", detector="visits",
        )
    if verdict.target.place_verification == "disputed":
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.DISPUTED_PLACE, severity=Severity.WARNING, subject_type=SubjectType.VISIT,
            subject=visit, user_id=user.id, shift_id=visit.shift_id, dedupe_key=f"disputed_place:visit:{visit.id}",
            detector="verifier", evidence={"place_id": place_id},
        )
    await db.flush()
    if shift is not None:
        await ingest.touch_shifts(db, {shift.id: when.occurred_at})
    await record_activity(db, action="fieldops_visit_started", actor_id=user.id, subject_type="Visit",
                          subject_id=visit.id, context={"uuid": str(visit.uuid), "channel": channel,
                                                        "check": visit.start_check})
    logger.info("fieldops.visit_started", visit_id=visit.id, user_id=user.id, channel=channel,
                check=visit.start_check, action=decision.action.value)
    return visit, True


async def end_visit(db: AsyncSession, act: Act, visit_uuid: uuid_lib.UUID, body: VisitEndIn) -> Visit:
    user = act.user
    visit = await own_visit(db, user, visit_uuid)
    if visit.status != VisitStatus.IN_PROGRESS.value:
        raise FieldOpsConflict("visit_not_in_progress", f"The visit is {visit.status}",
                               data={"visit": visit_brief(visit)})
    shift = await db.get(Shift, visit.shift_id) if visit.shift_id else None
    policy = policy_of(shift) if shift is not None else await resolve_policy(db, user)
    when = act.when(body.occurred)
    ended_at = max(when.occurred_at, visit.started_at)
    await ingest.write_checkpoint(db, user=user, send=act.send, derived=when, label=CheckpointLabel.VISIT_END.value,
                                  fix=body.fix, manual=body.manual_location, shift=shift, visit=visit,
                                  device_id=visit.device_id, policy=policy)
    if visit.channel == Channel.FIELD.value:
        verdict = await verify.evaluate(
            db, subject=visit, subject_type=SubjectType.VISIT, phase=CheckPhase.END, user_id=user.id, at=ended_at,
            place_id=visit.place_id, channel=visit.channel, policy=policy, enforce=False,
        )
        visit.end_check = verdict.result.value
    visit.ended_at = ended_at
    visit.end_received_at = act.send.received_at
    visit.end_time_basis = when.basis
    visit.end_client_timestamp = body.occurred.client_timestamp
    visit.outcome = body.outcome.value if body.outcome else visit.outcome
    visit.no_order_reason = body.no_order_reason.value if body.no_order_reason else visit.no_order_reason
    visit.follow_up_at = body.follow_up_at or visit.follow_up_at
    if body.notes:
        visit.notes = body.notes
    transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.COMPLETED.value, occurred_at=ended_at,
               time_basis=when.basis, source=TransitionSource.DEVICE, client_timestamp=body.occurred.client_timestamp,
               request_id=act.request_id, idempotency_key=act.idempotency_key)
    minutes = (ended_at - visit.started_at).total_seconds() / 60
    if minutes < policy.number("min_visit_minutes"):
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.SHORT_VISIT, severity=Severity.INFO, subject_type=SubjectType.VISIT,
            subject=visit, user_id=user.id, shift_id=visit.shift_id, dedupe_key=f"short_visit:visit:{visit.id}",
            detector="visits", evidence={"minutes": round(minutes, 2), "min": policy.min_visit_minutes},
        )
    await db.flush()
    if visit.shift_id is not None:
        await ingest.touch_shifts(db, {visit.shift_id: ended_at})
    return visit


async def cancel_visit(db: AsyncSession, act: Act, visit_uuid: uuid_lib.UUID, body: VisitCancelIn) -> Visit:
    user = act.user
    visit = await own_visit(db, user, visit_uuid)
    if visit.status not in (VisitStatus.IN_PROGRESS.value, VisitStatus.PLANNED.value):
        raise FieldOpsConflict("visit_not_cancellable", f"The visit is {visit.status}")
    when = act.when(body.occurred)
    now_at = max(when.occurred_at, visit.started_at) if visit.started_at else when.occurred_at
    visit.ended_at = now_at if visit.started_at else None
    visit.end_received_at = act.send.received_at
    visit.end_time_basis = when.basis if visit.started_at else None
    visit.cancellation_reason = body.reason.value
    visit.cancelled_at = act.send.received_at
    if body.note:
        visit.notes = body.note
    transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.CANCELLED.value, occurred_at=now_at,
               time_basis=when.basis, source=TransitionSource.DEVICE, reason_code=body.reason.value, note=body.note,
               client_timestamp=body.occurred.client_timestamp, request_id=act.request_id,
               idempotency_key=act.idempotency_key)
    await db.flush()
    return visit


async def join_visit(db: AsyncSession, act: Act, visit_uuid: uuid_lib.UUID, body: VisitJoinIn) -> VisitParticipant:
    """Joint working: join a colleague's in-progress visit as a participant (not a second visit)."""
    user = act.user
    visit = await db.scalar(select(Visit).where(Visit.uuid == visit_uuid))
    if visit is None:
        raise FieldOpsNotFound(f"Visit {visit_uuid} not found")
    if visit.user_id == user.id:
        raise FieldOpsRuleError("own_visit", "You own this visit; participants are other people")
    if visit.status != VisitStatus.IN_PROGRESS.value:
        raise FieldOpsConflict("visit_not_in_progress", f"The visit is {visit.status}")
    existing = await db.scalar(select(VisitParticipant).where(VisitParticipant.visit_id == visit.id,
                                                              VisitParticipant.user_id == user.id))
    if existing is not None:
        return existing
    when = act.when(body.occurred)
    participant = VisitParticipant(visit_id=visit.id, user_id=user.id, organization_id=visit.organization_id,
                                   participant_role=body.participant_role.value,
                                   joined_at=max(when.occurred_at, visit.started_at))
    db.add(participant)
    await db.flush()
    return participant


# ── manager side ────────────────────────────────────────────────────────────────

async def get_visit(db: AsyncSession, ref: str) -> Visit:
    visit = await db.scalar(select(Visit).where(by_ref(Visit, ref)))
    if visit is None:
        raise FieldOpsNotFound(f"Visit '{ref}' not found")
    return visit


async def correct_visit(db: AsyncSession, ref: str, body: VisitCorrectIn, *, actor: Any) -> Visit:
    visit = await get_visit(db, ref)
    if visit.row_version != body.row_version:
        raise FieldOpsConflict("row_version_conflict", "The visit changed since you loaded it; reload and retry",
                               data={"current_row_version": visit.row_version})
    started = body.started_at or visit.started_at
    ended = body.ended_at or visit.ended_at
    if started is not None and ended is not None and ended < started:
        raise FieldOpsRuleError("end_before_start", "The end cannot be before the start")
    changes: dict[str, list] = {}
    for field, basis_field in (("started_at", "start_time_basis"), ("ended_at", "end_time_basis")):
        new = getattr(body, field)
        if new is not None and new != getattr(visit, field):
            old = getattr(visit, field)
            changes[field] = [old.isoformat() if old else None, new.isoformat()]
            setattr(visit, field, new)
            setattr(visit, basis_field, TimeBasis.MANAGER.value)
    if body.outcome is not None and body.outcome.value != visit.outcome:
        changes["outcome"] = [visit.outcome, body.outcome.value]
        visit.outcome = body.outcome.value
    if body.notes is not None:
        visit.notes = body.notes
    if changes:
        now = dt.datetime.now(dt.UTC)
        visit.reviewed_by = actor.id
        visit.reviewed_at = now
        visit.visit_time_basis = "button"
        transition(db, visit, subject_type=SubjectType.VISIT, axis=TransitionAxis.REVIEW,
                   to_state=ReviewStatus.CORRECTED.value, occurred_at=now, time_basis=TimeBasis.MANAGER.value,
                   source=TransitionSource.MANAGER, note=body.reason, changes=changes)
    await db.flush()
    await record_activity(db, action="fieldops_visit_corrected", actor_id=actor.id, subject_type="Visit",
                          subject_id=visit.id, changes={"after": changes}, context={"reason": body.reason})
    return visit


async def review_visit(db: AsyncSession, ref: str, *, decision: str, note: str | None, actor: Any) -> Visit:
    visit = await get_visit(db, ref)
    if visit.status == VisitStatus.IN_PROGRESS.value:
        raise FieldOpsRuleError("visit_in_progress", "A visit in progress cannot be reviewed yet")
    to_state = ReviewStatus.APPROVED.value if decision == "approve" else ReviewStatus.REJECTED.value
    now = dt.datetime.now(dt.UTC)
    transition(db, visit, subject_type=SubjectType.VISIT, axis=TransitionAxis.REVIEW, to_state=to_state,
               occurred_at=now, time_basis=TimeBasis.MANAGER.value, source=TransitionSource.MANAGER, note=note)
    visit.reviewed_by = actor.id
    visit.reviewed_at = now
    await db.flush()
    return visit


async def cancel_as_manager(db: AsyncSession, ref: str, *, note: str | None, actor: Any) -> Visit:
    visit = await get_visit(db, ref)
    if visit.status not in (VisitStatus.IN_PROGRESS.value, VisitStatus.PLANNED.value):
        raise FieldOpsConflict("visit_not_cancellable", f"The visit is {visit.status}")
    now = dt.datetime.now(dt.UTC)
    if visit.started_at:
        visit.ended_at = max(now, visit.started_at)
        visit.end_time_basis = TimeBasis.MANAGER.value
    visit.cancellation_reason = VisitCancellationReason.MANAGER.value
    visit.cancelled_at = now
    transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.CANCELLED.value, occurred_at=now,
               time_basis=TimeBasis.MANAGER.value, source=TransitionSource.MANAGER,
               reason_code=VisitCancellationReason.MANAGER.value, note=note)
    await db.flush()
    return visit


async def mark_missed(db: AsyncSession, *, grace: dt.timedelta = dt.timedelta(hours=12), limit: int = 500) -> int:
    """Planned visits whose window passed without a start → ``missed`` (system, idempotent)."""
    now = dt.datetime.now(dt.UTC)
    rows = (await db.scalars(
        select(Visit).where(Visit.status == VisitStatus.PLANNED.value)
        .where(text("COALESCE(planned_end_at, planned_start_at) < :cutoff")).params(cutoff=now - grace)
        .limit(limit).execution_options(all_tenants=True)
    )).all()
    for visit in rows:
        transition(db, visit, subject_type=SubjectType.VISIT, to_state=VisitStatus.MISSED.value, occurred_at=now,
                   time_basis=TimeBasis.SERVER_RECEIPT.value, source=TransitionSource.SYSTEM, reason_code="window_passed")
    await db.flush()
    return len(rows)


__all__ = [
    "cancel_as_manager",
    "cancel_visit",
    "correct_visit",
    "end_visit",
    "entity_exists",
    "get_visit",
    "join_visit",
    "mark_missed",
    "registered",
    "review_visit",
    "start_visit",
]
