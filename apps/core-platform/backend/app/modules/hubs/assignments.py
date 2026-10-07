"""The user's hub for a day — resolution and date-effective writes (``user_hub_assignments``).

``hub_for(user, day)``: an assignment covering ``day`` (its ``hub_id`` may be NULL = explicitly no hub)
→ else the current employment record's ``hub_id`` → else NULL.

``assign(user, hub, from, to)`` SPLITS what it overlaps instead of refusing: assigning Tuesday only
inside an open-ended "Halol from 1 Oct" leaves "Halol 1 Oct–Mon", "Godhra Tue", "Halol Wed–…". The
overlapping rows are soft-deleted and their remnants re-created in the same transaction (flushed in
that order — the EXCLUDE constraint ignores soft-deleted rows), so history keeps who changed what.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, NotFoundError
from app.modules.hubs.enums import AssignmentSource
from app.modules.hubs.model import Hub, UserHubAssignment

logger = structlog.get_logger("app.hubs.assignments")

_ONE_DAY = dt.timedelta(days=1)


class HubAssignmentError(AppError):
    status_code = 422
    code = "hub_assignment_invalid"


@dataclass(frozen=True, slots=True)
class HubOfDay:
    hub_id: int | None
    source: str | None          # "assignment" | "employment" | None


async def organization_today(db: AsyncSession, organization_id: int) -> dt.date:
    """Today in the organization's timezone (its own, else its tenant's, else UTC) — business days are
    the organization's, never the device's."""
    from zoneinfo import ZoneInfo

    tz = await db.scalar(text(
        "SELECT COALESCE(o.timezone, t.timezone) FROM org_management.organizations o "
        "JOIN org_management.tenants t ON t.id = o.tenant_id WHERE o.id = :id"), {"id": organization_id})
    try:
        zone = ZoneInfo(tz) if tz else dt.UTC
    except Exception:  # noqa: BLE001 — an unknown zone name must not break a read
        zone = dt.UTC
    return dt.datetime.now(zone).date()


async def hub_of_day(db: AsyncSession, *, tenant_id: int, user_id: int, day: dt.date) -> HubOfDay:
    row = (await db.execute(text("""
        SELECT hub_id FROM user_hub_assignments
         WHERE tenant_id = :t AND user_id = :u AND deleted_at IS NULL
           AND valid_from <= :d AND (valid_to IS NULL OR valid_to >= :d)
         LIMIT 1
    """), {"t": tenant_id, "u": user_id, "d": day})).first()
    if row is not None:
        return HubOfDay(row.hub_id, "assignment")
    hub_id = await db.scalar(text("""
        SELECT hub_id FROM employment_records
         WHERE tenant_id = :t AND user_id = :u AND is_current AND deleted_at IS NULL AND hub_id IS NOT NULL
         ORDER BY id DESC LIMIT 1
    """), {"t": tenant_id, "u": user_id})
    return HubOfDay(hub_id, "employment") if hub_id is not None else HubOfDay(None, None)


async def hub_for(db: AsyncSession, *, tenant_id: int, user_id: int, day: dt.date) -> int | None:
    return (await hub_of_day(db, tenant_id=tenant_id, user_id=user_id, day=day)).hub_id


async def assign(db: AsyncSession, *, user: Any, hub_id: int | None, valid_from: dt.date,
                 valid_to: dt.date | None, source: AssignmentSource = AssignmentSource.MANAGER,
                 note: str | None = None) -> UserHubAssignment:
    """Make ``user``'s hub ``hub_id`` (NULL = none) for ``[valid_from, valid_to]``; split overlaps."""
    if valid_to is not None and valid_to < valid_from:
        raise HubAssignmentError("valid_to is before valid_from", data={"valid_from": str(valid_from)})
    if hub_id is not None:
        hub = await db.scalar(select(Hub).where(Hub.id == hub_id))
        if hub is None:
            raise NotFoundError(f"Hub {hub_id} not found")
    overlapping = (await db.scalars(select(UserHubAssignment).where(
        UserHubAssignment.user_id == user.id,
        UserHubAssignment.valid_from <= (valid_to or dt.date.max),
        (UserHubAssignment.valid_to.is_(None)) | (UserHubAssignment.valid_to >= valid_from),
    ))).all()
    remnants: list[UserHubAssignment] = []
    for row in overlapping:
        if row.valid_from < valid_from:
            remnants.append(_copy(row, row.valid_from, valid_from - _ONE_DAY))
        if valid_to is not None and (row.valid_to is None or row.valid_to > valid_to):
            remnants.append(_copy(row, valid_to + _ONE_DAY, row.valid_to))
        row.soft_delete(reason="superseded by a later hub assignment")
    await db.flush()                     # the soft deletes first: the EXCLUDE ignores deleted rows
    new = UserHubAssignment(user_id=user.id, organization_id=user.organization_id, hub_id=hub_id,
                            valid_from=valid_from, valid_to=valid_to, source=source.value, note=note)
    db.add_all([*remnants, new])
    await db.flush()
    logger.info("hubs.assignment_set", user_id=user.id, hub_id=hub_id, valid_from=str(valid_from),
                valid_to=str(valid_to) if valid_to else None, split=len(remnants))
    return new


def _copy(row: UserHubAssignment, start: dt.date, end: dt.date | None) -> UserHubAssignment:
    return UserHubAssignment(user_id=row.user_id, organization_id=row.organization_id, hub_id=row.hub_id,
                             valid_from=start, valid_to=end, source=row.source, note=row.note)


async def list_assignments(db: AsyncSession, *, user_id: int | None = None, hub_id: int | None = None,
                           day: dt.date | None = None, limit: int = 200) -> list[UserHubAssignment]:
    stmt = select(UserHubAssignment)
    if user_id is not None:
        stmt = stmt.where(UserHubAssignment.user_id == user_id)
    if hub_id is not None:
        stmt = stmt.where(UserHubAssignment.hub_id == hub_id)
    if day is not None:
        stmt = stmt.where(UserHubAssignment.valid_from <= day,
                          (UserHubAssignment.valid_to.is_(None)) | (UserHubAssignment.valid_to >= day))
    stmt = stmt.order_by(UserHubAssignment.user_id, UserHubAssignment.valid_from).limit(limit)
    return list((await db.scalars(stmt)).all())


__all__ = ["HubAssignmentError", "HubOfDay", "assign", "hub_for", "hub_of_day", "list_assignments",
           "organization_today"]
