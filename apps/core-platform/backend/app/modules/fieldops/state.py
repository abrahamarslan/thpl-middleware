"""The state machines — PURE. Which transitions exist; nothing else.

``service/transitions.py::transition`` is the only code that changes a ``status`` or
``review_status``; it calls :func:`assert_allowed` first and writes a
``fieldops.state_transitions`` row in the same transaction.

Shift lifecycle::

    scheduled ─start─▶ active ⇄ paused ─end─▶ completed
       │                 │   └─────────auto_close / supersede─▶ auto_closed
       └─cancel─┐        └─cancel (no visits)─┐
                ▼                             ▼
             cancelled ◀──────────────────────┘

Visit lifecycle::

    planned ─start─▶ in_progress ─end─▶ completed
       ├─(day over)─▶ missed          │
       └─cancel─▶ cancelled ◀─cancel──┘

Review axis (shifts, visits): ``not_required|pending → approved|rejected|corrected``, and a
decided review may be re-opened (``→ pending``) when new evidence arrives (late pings after
auto-close, a correction) or re-decided by a manager.
"""

from __future__ import annotations

from app.common.exception.errors import ConflictError
from app.modules.fieldops.enums import (
    PauseEndReason,
    ReviewStatus,
    ShiftStatus,
    SubjectType,
    TaskStatus,
    TransitionAxis,
    VisitStatus,
)

_S = ShiftStatus
_V = VisitStatus
_R = ReviewStatus

SHIFT_LIFECYCLE: dict[str | None, frozenset[str]] = {
    None: frozenset({_S.SCHEDULED.value, _S.ACTIVE.value}),
    _S.SCHEDULED.value: frozenset({_S.ACTIVE.value, _S.CANCELLED.value}),
    _S.ACTIVE.value: frozenset({_S.PAUSED.value, _S.COMPLETED.value, _S.AUTO_CLOSED.value, _S.CANCELLED.value}),
    _S.PAUSED.value: frozenset({_S.ACTIVE.value, _S.COMPLETED.value, _S.AUTO_CLOSED.value, _S.CANCELLED.value}),
    _S.COMPLETED.value: frozenset(),
    _S.AUTO_CLOSED.value: frozenset(),
    _S.CANCELLED.value: frozenset(),
}

VISIT_LIFECYCLE: dict[str | None, frozenset[str]] = {
    None: frozenset({_V.PLANNED.value, _V.IN_PROGRESS.value}),
    _V.PLANNED.value: frozenset({_V.IN_PROGRESS.value, _V.CANCELLED.value, _V.MISSED.value}),
    _V.IN_PROGRESS.value: frozenset({_V.COMPLETED.value, _V.CANCELLED.value}),
    _V.COMPLETED.value: frozenset(),
    _V.CANCELLED.value: frozenset(),
    _V.MISSED.value: frozenset(),
}

#: Pauses have a two-state life: open → ended (any end reason).
PAUSE_LIFECYCLE: dict[str | None, frozenset[str]] = {
    None: frozenset({"open"}),
    "open": frozenset(r.value for r in PauseEndReason),
}

TASK_LIFECYCLE: dict[str | None, frozenset[str]] = {
    None: frozenset({TaskStatus.SUBMITTED.value}),
    TaskStatus.SUBMITTED.value: frozenset({TaskStatus.VOIDED.value}),
    TaskStatus.VOIDED.value: frozenset(),
}

_DECIDED = frozenset({_R.APPROVED.value, _R.REJECTED.value, _R.CORRECTED.value})
REVIEW: dict[str | None, frozenset[str]] = {
    None: frozenset({_R.NOT_REQUIRED.value, _R.PENDING.value}),
    _R.NOT_REQUIRED.value: frozenset({_R.PENDING.value}) | _DECIDED,
    _R.PENDING.value: _DECIDED,
    _R.APPROVED.value: frozenset({_R.PENDING.value}) | _DECIDED,
    _R.REJECTED.value: frozenset({_R.PENDING.value}) | _DECIDED,
    _R.CORRECTED.value: frozenset({_R.PENDING.value}) | _DECIDED,
}

_TABLES = {
    (SubjectType.SHIFT.value, TransitionAxis.LIFECYCLE.value): SHIFT_LIFECYCLE,
    (SubjectType.VISIT.value, TransitionAxis.LIFECYCLE.value): VISIT_LIFECYCLE,
    (SubjectType.SHIFT_PAUSE.value, TransitionAxis.LIFECYCLE.value): PAUSE_LIFECYCLE,
    (SubjectType.VISIT_TASK.value, TransitionAxis.LIFECYCLE.value): TASK_LIFECYCLE,
    (SubjectType.SHIFT.value, TransitionAxis.REVIEW.value): REVIEW,
    (SubjectType.VISIT.value, TransitionAxis.REVIEW.value): REVIEW,
}


class InvalidTransition(ConflictError):
    code = "invalid_transition"


def allowed(subject_type: str, axis: str, from_state: str | None, to_state: str) -> bool:
    table = _TABLES.get((subject_type, axis))
    if table is None:
        return False
    return to_state in table.get(from_state, frozenset())


def assert_allowed(subject_type: str, axis: str, from_state: str | None, to_state: str) -> None:
    if not allowed(subject_type, axis, from_state, to_state):
        raise InvalidTransition(
            f"A {subject_type} cannot go from '{from_state}' to '{to_state}'",
            data={"subject_type": subject_type, "axis": axis, "from": from_state, "to": to_state},
        )


__all__ = [
    "PAUSE_LIFECYCLE", "REVIEW", "SHIFT_LIFECYCLE", "TASK_LIFECYCLE", "VISIT_LIFECYCLE",
    "InvalidTransition", "allowed", "assert_allowed",
]
