"""Visit tasks — what was done in a visit.

* The registry (``task_types.py``) validates the payload, the channel and the reference type.
* ``performed_at`` is the task's own business time, independent of the visit window: a
  payment collected after "end visit" is RECORDED (``after_visit_end``), never rejected. The
  window only bounds how late: ``policy.late_task_window_hours`` after the visit ended.
* A participant (joint working) may record tasks on the visit they joined.
* A replay of the same task uuid returns the existing task.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.enums import (
    AnomalyType,
    CheckpointLabel,
    Severity,
    SubjectType,
    TaskStatus,
    TimeBasis,
    TransitionAxis,
    TransitionSource,
    VisitStatus,
)
from app.modules.fieldops.errors import (
    FieldOpsConflict,
    FieldOpsNotFound,
    FieldOpsRuleError,
)
from app.modules.fieldops.model import Shift, Visit, VisitParticipant, VisitTask
from app.modules.fieldops.schema import TaskIn
from app.modules.fieldops.service import anomalies, ingest
from app.modules.fieldops.service.context import Act
from app.modules.fieldops.service.policy import resolve_policy
from app.modules.fieldops.service.shifts import policy_of
from app.modules.fieldops.service.transitions import record
from app.modules.fieldops.service.visits import registered
from app.modules.fieldops.task_types import spec_for

#: A task later than this after the visit ended is recorded AND flagged.
LATE_TASK_FLAG = dt.timedelta(hours=1)


async def _visit_for(db: AsyncSession, user: Any, visit_uuid: uuid_lib.UUID) -> Visit:
    visit = await db.scalar(select(Visit).where(Visit.uuid == visit_uuid))
    if visit is None:
        raise FieldOpsNotFound(f"Visit {visit_uuid} not found")
    if visit.user_id != user.id:
        joined = await db.scalar(select(VisitParticipant.id).where(VisitParticipant.visit_id == visit.id,
                                                                   VisitParticipant.user_id == user.id))
        if joined is None:
            raise FieldOpsNotFound(f"Visit {visit_uuid} not found")
    return visit


async def submit_task(db: AsyncSession, act: Act, visit_uuid: uuid_lib.UUID, body: TaskIn) -> tuple[VisitTask, bool]:
    user = act.user
    existing = await db.scalar(select(VisitTask).where(VisitTask.uuid == body.uuid)
                               .execution_options(include_deleted=True))
    if existing is not None:
        if existing.user_id != user.id:
            raise FieldOpsConflict("uuid_conflict", "This task uuid is already used")
        return existing, False

    visit = await _visit_for(db, user, visit_uuid)
    spec = spec_for(body.task_type.value)
    if visit.channel not in spec.channels:
        raise FieldOpsRuleError("task_type_not_allowed_for_channel",
                                f"A {spec.code.value} task cannot be recorded on a {visit.channel} visit",
                                data={"allowed_channels": sorted(spec.channels)})
    try:
        payload = spec.payload_model.model_validate(body.payload).model_dump(mode="json")
    except ValidationError as exc:
        raise FieldOpsRuleError("invalid_task_payload", f"The {spec.code.value} payload is invalid",
                                data={"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}
                                ) from None
    if body.amount is not None and not spec.carries_amount:
        raise FieldOpsRuleError("amount_not_allowed", f"A {spec.code.value} task carries no amount")
    if body.reference is not None:
        if body.reference.type not in spec.reference_types:
            raise FieldOpsRuleError("reference_type_not_allowed",
                                    f"A {spec.code.value} task cannot reference a {body.reference.type}",
                                    data={"allowed": sorted(spec.reference_types)})
        if not await registered(db, body.reference.type):
            raise FieldOpsRuleError("reference_type_not_registered",
                                    f"'{body.reference.type}' is not a registered entity type yet",
                                    data={"type": body.reference.type})

    shift = await db.get(Shift, visit.shift_id) if visit.shift_id else None
    policy = policy_of(shift) if shift is not None else await resolve_policy(db, user)
    when = act.when(body.occurred)
    if visit.status == VisitStatus.CANCELLED.value:
        raise FieldOpsConflict("visit_cancelled", "The visit was cancelled; its tasks cannot be recorded")
    if visit.status not in (VisitStatus.IN_PROGRESS.value, VisitStatus.COMPLETED.value):
        raise FieldOpsConflict("visit_not_started", f"The visit is {visit.status}")
    after_end = visit.ended_at is not None and when.occurred_at > visit.ended_at
    if after_end and when.occurred_at - visit.ended_at > dt.timedelta(hours=int(policy.late_task_window_hours)):
        raise FieldOpsRuleError("late_task_window_passed", "The visit ended too long ago to add tasks",
                                data={"window_hours": policy.late_task_window_hours})

    task = VisitTask(
        uuid=body.uuid, visit_id=visit.id, user_id=user.id, organization_id=visit.organization_id,
        task_type=spec.code.value, status=TaskStatus.SUBMITTED.value, performed_at=when.occurred_at,
        received_at=act.send.received_at, time_basis=when.basis, client_timestamp=body.occurred.client_timestamp,
        after_visit_end=after_end, payload=payload,
        reference_type=body.reference.type if body.reference else None,
        reference_id=body.reference.id if body.reference else None,
        reference_uuid=body.reference.uuid if body.reference else None,
        amount=body.amount, currency_code=body.currency_code,
    )
    db.add(task)
    await db.flush()
    record(db, subject=task, subject_type=SubjectType.VISIT_TASK, axis=TransitionAxis.LIFECYCLE, from_state=None,
           to_state=TaskStatus.SUBMITTED.value, occurred_at=when.occurred_at, time_basis=when.basis,
           source=TransitionSource.DEVICE, client_timestamp=body.occurred.client_timestamp,
           request_id=act.request_id, idempotency_key=act.idempotency_key)
    if body.fix is not None:
        await ingest.write_checkpoint(db, user=user, send=act.send, derived=when,
                                      label=CheckpointLabel.TASK_SUBMITTED.value, fix=body.fix, manual=None,
                                      shift=shift, visit=visit, device_id=visit.device_id, policy=policy)
    if after_end and when.occurred_at - visit.ended_at > LATE_TASK_FLAG:
        await anomalies.open_anomaly(
            db, anomaly_type=AnomalyType.LATE_TASK, severity=Severity.INFO, subject_type=SubjectType.VISIT_TASK,
            subject=task, user_id=user.id, shift_id=visit.shift_id, dedupe_key=f"late_task:task:{task.id}",
            detector="tasks", evidence={"visit_ended_at": visit.ended_at.isoformat(),
                                        "performed_at": when.occurred_at.isoformat()},
        )
    if visit.shift_id is not None:
        await ingest.touch_shifts(db, {visit.shift_id: when.occurred_at})
    await db.flush()
    return task, True


async def void_task(db: AsyncSession, act: Act, task_uuid: uuid_lib.UUID, *, reason: str) -> VisitTask:
    user = act.user
    task = await db.scalar(select(VisitTask).where(VisitTask.uuid == task_uuid, VisitTask.user_id == user.id))
    if task is None:
        raise FieldOpsNotFound(f"Task {task_uuid} not found")
    if task.status == TaskStatus.VOIDED.value:
        return task
    now = dt.datetime.now(dt.UTC)
    record(db, subject=task, subject_type=SubjectType.VISIT_TASK, axis=TransitionAxis.LIFECYCLE,
           from_state=task.status, to_state=TaskStatus.VOIDED.value, occurred_at=now,
           time_basis=TimeBasis.SERVER_RECEIPT.value, source=TransitionSource.DEVICE, note=reason,
           request_id=act.request_id, idempotency_key=act.idempotency_key)
    task.status = TaskStatus.VOIDED.value
    task.void_reason = reason
    await db.flush()
    return task


async def tasks_of(db: AsyncSession, visit_id: int) -> list[VisitTask]:
    return list((await db.scalars(select(VisitTask).where(VisitTask.visit_id == visit_id)
                                  .order_by(VisitTask.performed_at))).all())


__all__ = ["submit_task", "tasks_of", "void_task"]
