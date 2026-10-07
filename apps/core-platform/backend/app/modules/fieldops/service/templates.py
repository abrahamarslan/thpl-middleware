"""Shift templates: administration, the occurrence that applies at an instant, and materialization
(docs/fieldops/shift-templates.md).

``occurrence(template, at, tz)`` — the template's window that ``at`` belongs to, in the template's
timezone (else the organization's): today's ``[start, end)`` if ``at`` is before today's end, else
nothing; an overnight template (``end_day_offset = 1``) first checks YESTERDAY's occurrence, which
is still running at 01:00. Days of the week and the validity window gate the occurrence's DATE.

``materialize`` turns (template, occurrence) into the plan fields of a shift; ``service/shifts.py``
calls it when a user starts with no scheduled shift. The template's values are copied into
``template_snapshot`` — editing the template never rewrites a past shift.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.scope import require_organization_id
from app.modules.activity.recorder import record_activity
from app.modules.fieldops.endpoints import SIDES, EndpointValue, from_input
from app.modules.fieldops.errors import FieldOpsConflict, FieldOpsNotFound, FieldOpsRuleError
from app.modules.fieldops.model import ShiftTemplate
from app.modules.fieldops.service.common import org_timezone

logger = structlog.get_logger("app.fieldops.templates")


@dataclass(frozen=True, slots=True)
class Occurrence:
    day: dt.date                   # the template's local business date
    planned_start_at: dt.datetime  # UTC
    planned_end_at: dt.datetime    # UTC
    timezone: str


def _zone(name: str | None) -> ZoneInfo | dt.timezone:
    try:
        return ZoneInfo(name) if name else dt.UTC
    except Exception:  # noqa: BLE001 — an unknown zone must not break a start
        return dt.UTC


def _window(template: Any, day: dt.date, zone) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(day, template.start_local_time, tzinfo=zone)
    end = dt.datetime.combine(day + dt.timedelta(days=int(template.end_day_offset or 0)),
                              template.end_local_time, tzinfo=zone)
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


def applies_on(template: Any, day: dt.date) -> bool:
    if template.status != "active":
        return False
    if day.isoweekday() not in set(template.days_of_week or (1, 2, 3, 4, 5, 6, 7)):
        return False
    if template.valid_from is not None and day < template.valid_from:
        return False
    return not (template.valid_until is not None and day > template.valid_until)


def occurrence(template: Any, at: dt.datetime, tz_name: str | None) -> Occurrence | None:
    """The occurrence ``at`` falls in (it may be BEFORE its start — an early start), or None when the
    day's window is over / the day is excluded. PURE."""
    name = template.timezone or tz_name or "UTC"
    zone = _zone(name)
    local_day = at.astimezone(zone).date()
    candidates = [local_day]
    if int(template.end_day_offset or 0) == 1:
        candidates.insert(0, local_day - dt.timedelta(days=1))
    for day in candidates:
        if not applies_on(template, day):
            continue
        start, end = _window(template, day, zone)
        if at < end and (day == local_day or at >= start):
            return Occurrence(day, start, end, name)
    return None


def next_occurrences(template: Any, at: dt.datetime, tz_name: str | None, *, days: int = 2) -> list[Occurrence]:
    """Occurrences whose window has not ended, starting with the one ``at`` is in (virtual entries)."""
    name = template.timezone or tz_name or "UTC"
    zone = _zone(name)
    out = []
    first = at.astimezone(zone).date() - dt.timedelta(days=int(template.end_day_offset or 0))
    for i in range(days + int(template.end_day_offset or 0)):
        day = first + dt.timedelta(days=i)
        if not applies_on(template, day):
            continue
        start, end = _window(template, day, zone)
        if end > at:
            out.append(Occurrence(day, start, end, name))
    return out[:days]


def title_for(template: Any, day: dt.date) -> str:
    if not template.title_pattern:
        return template.name
    try:
        return template.title_pattern.format(name=template.name, date=day, weekday=day.strftime("%A"))[:200]
    except (KeyError, IndexError, ValueError):
        return template.name


def snapshot(template: Any) -> dict[str, Any]:
    return {
        "uuid": str(template.uuid), "code": template.code, "name": template.name, "work_type": template.work_type,
        "start_local_time": template.start_local_time.isoformat(), "end_local_time": template.end_local_time.isoformat(),
        "end_day_offset": template.end_day_offset, "timezone": template.timezone,
        "days_of_week": list(template.days_of_week or ()), "row_version": template.row_version,
        **{f"{side}": EndpointValue.of(template, side).as_dict() for side in SIDES},
    }


def materialize(template: Any, occ: Occurrence) -> dict[str, Any]:
    """The plan fields a shift takes from (template, occurrence)."""
    fields: dict[str, Any] = {
        "planned_start_at": occ.planned_start_at, "planned_end_at": occ.planned_end_at,
        "title": title_for(template, occ.day), "work_type": template.work_type, "template_id": template.id,
        "template_snapshot": snapshot(template),
    }
    for side in SIDES:
        for name, value in EndpointValue.of(template, side).as_dict().items():
            fields[f"{side}_{name}"] = value
    return fields


# ── lookups ─────────────────────────────────────────────────────────────────────

async def by_code(db: AsyncSession, code: str | None) -> ShiftTemplate | None:
    if not code:
        return None
    return await db.scalar(select(ShiftTemplate).where(func.upper(ShiftTemplate.code) == code.strip().upper()))


async def get_template(db: AsyncSession, ref: str) -> ShiftTemplate:
    try:
        cond = ShiftTemplate.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        cond = ShiftTemplate.id == int(ref) if str(ref).isdigit() \
            else func.upper(ShiftTemplate.code) == str(ref).strip().upper()
    row = await db.scalar(select(ShiftTemplate).where(cond))
    if row is None:
        raise FieldOpsNotFound(f"Shift template '{ref}' not found")
    return row


async def list_templates(db: AsyncSession, *, status: str | None = None) -> list[ShiftTemplate]:
    stmt = select(ShiftTemplate)
    if status is not None:
        stmt = stmt.where(ShiftTemplate.status == status)
    return list((await db.scalars(stmt.order_by(ShiftTemplate.code))).all())


# ── administration ──────────────────────────────────────────────────────────────

async def _apply_endpoints(db: AsyncSession, row: ShiftTemplate, body: Any, *, tenant_id: int) -> None:
    for side in SIDES:
        if side in body.model_fields_set:
            value = await from_input(db, getattr(body, side), tenant_id=tenant_id,
                                     organization_id=row.organization_id)
            value.apply(row, side)


def _check_window(row: ShiftTemplate) -> None:
    if int(row.end_day_offset or 0) == 0 and row.end_local_time <= row.start_local_time:
        raise FieldOpsRuleError("invalid_template_window",
                                "The end must be after the start (or set end_day_offset = 1 for an overnight shift)")
    if row.planned_minutes > 24 * 60:
        raise FieldOpsRuleError("invalid_template_window", "A template window cannot exceed 24 hours")


async def create_template(db: AsyncSession, body: Any, *, actor: Any) -> ShiftTemplate:
    organization_id = await require_organization_id(db)
    code = body.code.strip().upper()
    if await by_code(db, code) is not None:
        raise FieldOpsConflict("template_code_exists", f"A shift template with code {code} already exists",
                               data={"code": code})
    row = ShiftTemplate(
        organization_id=organization_id, code=code, name=body.name, description=body.description,
        title_pattern=body.title_pattern, work_type=body.work_type.value, start_local_time=body.start_local_time,
        end_local_time=body.end_local_time, end_day_offset=body.end_day_offset, timezone=body.timezone,
        days_of_week=sorted(set(body.days_of_week)), valid_from=body.valid_from, valid_until=body.valid_until,
        status=body.status,
    )
    _check_window(row)
    await _apply_endpoints(db, row, body, tenant_id=actor.tenant_id)
    db.add(row)
    await db.flush()
    await record_activity(db, action="fieldops_shift_template_created", actor_id=actor.id,
                          subject_type="ShiftTemplate", subject_id=row.id, context={"code": code})
    logger.info("fieldops.template_created", template_id=row.id, code=code)
    return row


async def update_template(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> ShiftTemplate:
    row = await get_template(db, ref)
    if row.row_version != body.row_version:
        raise FieldOpsConflict("row_version_conflict", "The template changed since you loaded it; reload and retry",
                               data={"current_row_version": row.row_version})
    data = body.model_dump(exclude_unset=True, exclude={"row_version", "start", "end"})
    for key, value in data.items():
        if key == "work_type" and value is not None:
            value = value.value if hasattr(value, "value") else value
        if key == "days_of_week" and value is not None:
            value = sorted(set(value))
        setattr(row, key, value)
    _check_window(row)
    await _apply_endpoints(db, row, body, tenant_id=actor.tenant_id)
    await db.flush()
    await record_activity(db, action="fieldops_shift_template_updated", actor_id=actor.id,
                          subject_type="ShiftTemplate", subject_id=row.id, context={"fields": sorted(data)})
    return row


async def delete_template(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> None:
    row = await get_template(db, ref)
    row.soft_delete(reason=reason, by=actor.id)
    await db.flush()


async def preview(db: AsyncSession, template: ShiftTemplate, *, user: Any, at: dt.datetime) -> dict[str, Any]:
    tz = await org_timezone(db, user.organization_id)
    occ = occurrence(template, at, tz)
    return {"template": template.code, "at": at.isoformat(),
            "occurrence": None if occ is None else {
                "day": occ.day.isoformat(), "planned_start_at": occ.planned_start_at.isoformat(),
                "planned_end_at": occ.planned_end_at.isoformat(), "timezone": occ.timezone,
                "title": title_for(template, occ.day)},
            "next": [{"day": o.day.isoformat(), "planned_start_at": o.planned_start_at.isoformat(),
                      "planned_end_at": o.planned_end_at.isoformat()}
                     for o in next_occurrences(template, at, tz, days=3)]}


__all__ = [
    "Occurrence", "applies_on", "by_code", "create_template", "delete_template", "get_template", "list_templates",
    "materialize", "next_occurrences", "occurrence", "preview", "snapshot", "title_for", "update_template",
]
