"""Read queries for the field-ops API. SQL only — rules live in ``service/``.

Lists are SLIM at the SQL layer (``load_only``) — the columns a list renders, nothing more;
details load their children in a fixed number of queries (no relationship lazy loads: the
field-ops models declare none, so nothing can fire implicitly under AsyncSession).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.fieldops.enums import (
    OPEN_SHIFT_STATUSES,
    AnomalyState,
    ReviewStatus,
    VisitStatus,
)
from app.modules.fieldops.model import (
    Anomaly,
    LocationCheck,
    Shift,
    ShiftMetrics,
    ShiftPause,
    Visit,
    VisitParticipant,
    VisitTask,
)
from app.modules.fieldops.scope import Visible

_SHIFT_SLIM = (Shift.id, Shift.uuid, Shift.user_id, Shift.organization_id, Shift.shift_date, Shift.status,
               Shift.review_status, Shift.started_at, Shift.ended_at, Shift.paused_since, Shift.pause_count,
               Shift.wall_clock_minutes, Shift.paid_minutes, Shift.duration_basis, Shift.shift_code, Shift.title,
               Shift.work_type, Shift.source, Shift.planned_start_at, Shift.planned_end_at, Shift.auto_close_at,
               Shift.start_check, Shift.start_distance_m, Shift.end_check, Shift.end_distance_m, Shift.hub_id,
               Shift.template_id, Shift.policy_snapshot, Shift.start_mode, Shift.start_hub_id, Shift.start_place_id,
               Shift.start_enforcement, Shift.start_radius_m, Shift.end_mode, Shift.end_hub_id, Shift.end_place_id,
               Shift.end_enforcement, Shift.end_radius_m)
_VISIT_SLIM = (Visit.id, Visit.uuid, Visit.user_id, Visit.organization_id, Visit.shift_id, Visit.channel,
               Visit.status, Visit.review_status, Visit.purpose, Visit.account_type, Visit.account_id,
               Visit.place_id, Visit.started_at, Visit.ended_at, Visit.start_check, Visit.outcome)


def _scoped(stmt, visible: Visible | None, user_col, org_col):
    if visible is None:
        return stmt
    clause = visible.filter(user_col, org_col)
    return stmt if clause is None else stmt.where(clause)


async def list_shifts(
    db: AsyncSession, *, visible: Visible | None, user_id: int | None = None, date_from: dt.date | None = None,
    date_to: dt.date | None = None, status: str | None = None, review_status: str | None = None,
    limit: int = 50, offset: int = 0, statuses: tuple[str, ...] | None = None,
    planned_from: dt.datetime | None = None,
) -> list[Shift]:
    stmt = select(Shift).options(load_only(*_SHIFT_SLIM))
    if statuses:
        stmt = stmt.where(Shift.status.in_(statuses))
    if planned_from is not None:
        stmt = stmt.where(Shift.planned_end_at >= planned_from)
    stmt = _scoped(stmt, visible, Shift.user_id, Shift.organization_id)
    if user_id is not None:
        stmt = stmt.where(Shift.user_id == user_id)
    if date_from is not None:
        stmt = stmt.where(Shift.shift_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Shift.shift_date <= date_to)
    if status is not None:
        stmt = stmt.where(Shift.status == status)
    if review_status is not None:
        stmt = stmt.where(Shift.review_status == review_status)
    stmt = stmt.order_by(Shift.shift_date.desc(), Shift.started_at.desc().nulls_first(),
                         Shift.planned_start_at.asc().nulls_last()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


async def list_visits(
    db: AsyncSession, *, visible: Visible | None, user_id: int | None = None, shift_id: int | None = None,
    date_from: dt.datetime | None = None, date_to: dt.datetime | None = None, status: str | None = None,
    channel: str | None = None, review_status: str | None = None, account_type: str | None = None,
    account_id: int | None = None, limit: int = 50, offset: int = 0,
) -> list[Visit]:
    stmt = select(Visit).options(load_only(*_VISIT_SLIM))
    stmt = _scoped(stmt, visible, Visit.user_id, Visit.organization_id)
    for column, value in ((Visit.user_id, user_id), (Visit.shift_id, shift_id), (Visit.status, status),
                          (Visit.channel, channel), (Visit.review_status, review_status),
                          (Visit.account_type, account_type), (Visit.account_id, account_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    if date_from is not None:
        stmt = stmt.where(Visit.started_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Visit.started_at < date_to)
    stmt = stmt.order_by(Visit.started_at.desc().nulls_last()).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


async def visits_of_shift(db: AsyncSession, shift_id: int) -> list[Visit]:
    return list((await db.scalars(select(Visit).options(load_only(*_VISIT_SLIM))
                                  .where(Visit.shift_id == shift_id).order_by(Visit.started_at))).all())


async def pauses_of(db: AsyncSession, shift_id: int) -> list[ShiftPause]:
    return list((await db.scalars(select(ShiftPause).where(ShiftPause.shift_id == shift_id)
                                  .order_by(ShiftPause.started_at))).all())


async def open_pause_of(db: AsyncSession, shift_id: int) -> ShiftPause | None:
    return await db.scalar(select(ShiftPause).where(ShiftPause.shift_id == shift_id, ShiftPause.ended_at.is_(None)))


async def metrics_of(db: AsyncSession, shift_id: int) -> ShiftMetrics | None:
    return await db.scalar(select(ShiftMetrics).where(ShiftMetrics.shift_id == shift_id))


async def open_anomalies_of_shift(db: AsyncSession, shift_id: int) -> list[Anomaly]:
    return list((await db.scalars(select(Anomaly).where(
        Anomaly.shift_id == shift_id, Anomaly.status.in_((AnomalyState.OPEN.value, AnomalyState.ACKNOWLEDGED.value))
    ).order_by(Anomaly.detected_at))).all())


async def participants_of(db: AsyncSession, visit_id: int) -> list[VisitParticipant]:
    return list((await db.scalars(select(VisitParticipant).where(VisitParticipant.visit_id == visit_id))).all())


async def checks_of(db: AsyncSession, subject_type: str, subject_id: int) -> list[LocationCheck]:
    return list((await db.scalars(select(LocationCheck).where(
        LocationCheck.subject_type == subject_type, LocationCheck.subject_id == subject_id,
    ).order_by(LocationCheck.evaluated_at))).all())


async def tasks_of(db: AsyncSession, visit_id: int) -> list[VisitTask]:
    return list((await db.scalars(select(VisitTask).where(VisitTask.visit_id == visit_id)
                                  .order_by(VisitTask.performed_at))).all())


async def track(db: AsyncSession, shift: Shift, *, simplify_m: float = 0.0, limit: int = 20_000) -> list:
    """The shift's fixes (by user + window, so unlinked fixes count too), time-ordered. Server-side
    thinning: a point is kept when it is ``simplify_m`` away from the last kept one, or is a checkpoint."""
    end = shift.ended_at or dt.datetime.now(dt.UTC)
    rows = (await db.execute(text("""
        SELECT uuid, occurred_at, ST_Y(coordinates::geometry) AS lat, ST_X(coordinates::geometry) AS lng,
               accuracy_m, kind, checkpoint_label, quality_flags, coordinates
          FROM fieldops.location_pings
         WHERE tenant_id = :tenant AND user_id = :user AND occurred_at BETWEEN :start AND :end
           AND coordinates IS NOT NULL
         ORDER BY occurred_at
         LIMIT :limit
    """), {"tenant": shift.tenant_id, "user": shift.user_id, "start": shift.started_at, "end": end,
           "limit": limit})).all()
    if simplify_m <= 0:
        return rows
    from app.modules.geo.distance import distance_m

    kept = []
    for row in rows:
        if row.kind == "checkpoint" or not kept or \
                distance_m((kept[-1].lat, kept[-1].lng), (row.lat, row.lng)) >= simplify_m:
            kept.append(row)
    return kept


async def live(db: AsyncSession, visible: Visible | None, *, tenant_id: int, on_shift_only: bool = False) -> list:
    """Last known positions + the open shift / in-progress visit of each visible user.

    Raw SQL bypasses the ORM tenant filter, so the tenant is an explicit parameter here."""
    rows = (await db.execute(text(f"""
        SELECT l.user_id, l.organization_id, ST_Y(l.coordinates::geometry) AS lat,
               ST_X(l.coordinates::geometry) AS lng, l.accuracy_m, l.recorded_at,
               s.uuid AS shift_uuid, s.status AS shift_status, v.uuid AS visit_uuid
          FROM user_live_locations l
          LEFT JOIN fieldops.shifts s ON s.tenant_id = l.tenant_id AND s.user_id = l.user_id
               AND s.status = ANY(:open) AND s.deleted_at IS NULL
          LEFT JOIN fieldops.visits v ON v.tenant_id = l.tenant_id AND v.user_id = l.user_id
               AND v.status = 'in_progress' AND v.deleted_at IS NULL
         WHERE l.tenant_id = :tenant {"AND s.id IS NOT NULL" if on_shift_only else ""}
         ORDER BY l.recorded_at DESC NULLS LAST
    """), {"open": list(OPEN_SHIFT_STATUSES), "tenant": tenant_id})).all()
    if visible is None or visible.unrestricted:
        return rows
    return [r for r in rows if visible.allows_user(r.user_id, r.organization_id)]


async def review_queue(db: AsyncSession, visible: Visible | None, *, limit: int = 100) -> tuple[list, list, list]:
    shifts = await list_shifts(db, visible=visible, review_status=ReviewStatus.PENDING.value, limit=limit)
    visits = await list_visits(db, visible=visible, review_status=ReviewStatus.PENDING.value, limit=limit)
    stmt = select(Anomaly).where(Anomaly.status == AnomalyState.OPEN.value)
    stmt = _scoped(stmt, visible, Anomaly.user_id, Anomaly.organization_id)
    anomalies = list((await db.scalars(stmt.order_by(Anomaly.detected_at.desc()).limit(limit))).all())
    return shifts, visits, anomalies


async def list_anomalies(db: AsyncSession, *, visible: Visible | None, status: str | None, anomaly_type: str | None,
                         severity: str | None, shift_id: int | None = None, limit: int = 100,
                         offset: int = 0) -> list[Anomaly]:
    stmt = select(Anomaly)
    stmt = _scoped(stmt, visible, Anomaly.user_id, Anomaly.organization_id)
    for column, value in ((Anomaly.status, status), (Anomaly.anomaly_type, anomaly_type),
                          (Anomaly.severity, severity), (Anomaly.shift_id, shift_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    return list((await db.scalars(stmt.order_by(Anomaly.detected_at.desc()).limit(limit).offset(offset))).all())


async def current_of(db: AsyncSession, user_id: int) -> tuple[Shift | None, ShiftPause | None, Visit | None]:
    shift = await db.scalar(select(Shift).where(Shift.user_id == user_id, Shift.status.in_(OPEN_SHIFT_STATUSES)))
    pause = await open_pause_of(db, shift.id) if shift is not None else None
    visit = await db.scalar(select(Visit).where(Visit.user_id == user_id,
                                                Visit.status == VisitStatus.IN_PROGRESS.value))
    return shift, pause, visit


async def my_shifts(db: AsyncSession, user_id: int, *, date_from: dt.date | None, date_to: dt.date | None,
                    limit: int = 31, status: str | None = None, upcoming: bool = False) -> list[Shift]:
    """My shifts: open first, then scheduled by planned start, then history (newest first). ``upcoming``:
    only scheduled/open shifts whose planned window has not ended."""
    if upcoming:
        rows = await list_shifts(db, visible=None, user_id=user_id, statuses=("scheduled", "active", "paused"),
                                 planned_from=dt.datetime.now(dt.UTC), limit=limit)
        rows += [r for r in await list_shifts(db, visible=None, user_id=user_id, statuses=("active", "paused"),
                                              limit=2) if r not in rows]
    else:
        rows = await list_shifts(db, visible=None, user_id=user_id, date_from=date_from, date_to=date_to,
                                 status=status, limit=limit)
    rank = {"active": 0, "paused": 0, "scheduled": 1}
    far = dt.datetime.max.replace(tzinfo=dt.UTC)
    return sorted(rows, key=lambda r: (rank.get(r.status, 2),
                                       (r.planned_start_at or far) if r.status == "scheduled" else far,
                                       -(r.shift_date.toordinal())))


async def my_visits(db: AsyncSession, user_id: int, *, day_start: dt.datetime | None, day_end: dt.datetime | None,
                    limit: int = 200) -> list[Visit]:
    return await list_visits(db, visible=None, user_id=user_id, date_from=day_start, date_to=day_end, limit=limit)
