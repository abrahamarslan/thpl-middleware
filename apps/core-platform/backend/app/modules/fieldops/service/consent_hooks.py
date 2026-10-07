"""Field operations' reaction to consent withdrawal (registered with ``compliance.consents``).

A withdrawn ``location_tracking`` consent ENDS the user's open shift now (``end_reason =
consent_withdrawn``, closed as completed at the server's receipt time): tracking must not carry on
after the person said stop (DPDP Act 2023). The app sees the shift closed on its next call.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.consents import on_withdrawal

logger = structlog.get_logger("app.fieldops.consent")


async def end_shift_on_withdrawal(db: AsyncSession, user: Any, consent_type: str) -> None:
    if consent_type != "location_tracking":
        return
    from app.modules.fieldops.enums import (
        DurationBasis,
        EndedBy,
        PauseEndReason,
        ShiftEndReason,
        ShiftStatus,
        TimeBasis,
        TransitionSource,
        VisitCancellationReason,
    )
    from app.modules.fieldops.service.common import open_shift_of
    from app.modules.fieldops.service.shifts import close_shift

    shift = await open_shift_of(db, user.id)
    if shift is None:
        return
    now = dt.datetime.now(dt.UTC)
    await close_shift(
        db, shift, ended_at=now, time_basis=TimeBasis.SERVER_RECEIPT.value, received_at=now, ended_by=EndedBy.USER,
        end_reason=ShiftEndReason.CONSENT_WITHDRAWN, to_status=ShiftStatus.COMPLETED, source=TransitionSource.SERVER,
        duration_basis=DurationBasis.DEVICE_REPORTED, pause_reason=PauseEndReason.SHIFT_ENDED,
        visit_reason=VisitCancellationReason.USER,
    )
    logger.info("fieldops.shift_ended_consent_withdrawn", shift_id=shift.id, user_id=user.id)


on_withdrawal(end_shift_on_withdrawal)

__all__ = ["end_shift_on_withdrawal"]
