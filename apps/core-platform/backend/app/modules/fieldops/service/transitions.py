"""The ONLY writer of ``status`` / ``review_status`` on shifts and visits (and the only
recorder of pause and task transitions).

``transition`` validates the move against ``state.py``, sets the column, and appends a
``fieldops.state_transitions`` row in the caller's transaction — so a status can never
change without its history, and a history row can never exist without the change.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.tenancy import current_actor
from app.modules.fieldops.enums import (
    SubjectType,
    TimeBasis,
    TransitionAxis,
    TransitionSource,
)
from app.modules.fieldops.model import StateTransition
from app.modules.fieldops.state import assert_allowed

_COLUMN = {TransitionAxis.LIFECYCLE.value: "status", TransitionAxis.REVIEW.value: "review_status"}


def record(
    db: AsyncSession,
    *,
    subject: Any,
    subject_type: SubjectType | str,
    axis: TransitionAxis | str,
    from_state: str | None,
    to_state: str,
    occurred_at: dt.datetime,
    time_basis: TimeBasis | str,
    source: TransitionSource | str,
    client_timestamp: dt.datetime | None = None,
    reason_code: str | None = None,
    note: str | None = None,
    changes: dict | None = None,
    request_id: str | None = None,
    idempotency_key: uuid_lib.UUID | None = None,
) -> StateTransition:
    """Append a history row (validated). Use :func:`transition` for status columns."""
    subject_type = SubjectType(subject_type).value
    axis = TransitionAxis(axis).value
    assert_allowed(subject_type, axis, from_state, to_state)
    actor = current_actor()
    row = StateTransition(
        tenant_id=subject.tenant_id, organization_id=subject.organization_id,
        subject_type=subject_type, subject_id=subject.id, subject_uuid=getattr(subject, "uuid", None),
        axis=axis, from_state=from_state, to_state=to_state, reason_code=reason_code, note=note,
        occurred_at=occurred_at, time_basis=TimeBasis(time_basis).value, client_timestamp=client_timestamp,
        actor_user_id=actor.user_id, actor_label=actor.name, source=TransitionSource(source).value,
        request_id=request_id, idempotency_key=idempotency_key, changes=changes,
    )
    db.add(row)
    return row


def transition(
    db: AsyncSession,
    subject: Any,
    *,
    subject_type: SubjectType | str,
    to_state: str,
    occurred_at: dt.datetime,
    time_basis: TimeBasis | str,
    source: TransitionSource | str,
    axis: TransitionAxis | str = TransitionAxis.LIFECYCLE,
    new: bool = False,
    **extra: Any,
) -> StateTransition:
    """Move ``subject`` to ``to_state`` on ``axis`` and record it. ``new=True`` for a row being created
    (its transition is from ``None``). The subject must already have an id (flush first)."""
    axis_value = TransitionAxis(axis).value
    column = _COLUMN[axis_value]
    from_state = None if new else getattr(subject, column)
    row = record(db, subject=subject, subject_type=subject_type, axis=axis_value, from_state=from_state,
                  to_state=to_state, occurred_at=occurred_at, time_basis=time_basis, source=source, **extra)
    setattr(subject, column, to_state)
    return row


__all__ = ["record", "transition"]
