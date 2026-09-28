"""Small shared lookups for the field-ops services."""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.enums import OPEN_SHIFT_STATUSES, VisitStatus
from app.modules.fieldops.errors import FieldOpsNotFound
from app.modules.fieldops.model import Shift, Visit


async def org_timezone(db: AsyncSession, organization_id: int) -> str | None:
    """The organization's operational timezone, else its tenant's (business days are THEIRS, not the device's)."""
    return await db.scalar(text(
        "SELECT COALESCE(o.timezone, t.timezone) FROM org_management.organizations o "
        "JOIN org_management.tenants t ON t.id = o.tenant_id WHERE o.id = :id"
    ), {"id": organization_id})


async def has_location_consent(db: AsyncSession, user_id: int) -> bool:
    """An active, given ``location_tracking`` consent (DPDP) — compliance.consent_records."""
    return bool(await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM consent_records WHERE user_id = :u AND consent_type = 'location_tracking' "
        "AND consent_given AND is_active AND withdrawn_at IS NULL AND deleted_at IS NULL)"
    ), {"u": user_id}))


async def media_exists(db: AsyncSession, media_uuid: uuid_lib.UUID, tenant_id: int) -> bool:
    return bool(await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM media.items WHERE uuid = :u AND tenant_id = :t AND deleted_at IS NULL)"),
        {"u": media_uuid, "t": tenant_id}))


async def open_shift_of(db: AsyncSession, user_id: int) -> Shift | None:
    return await db.scalar(select(Shift).where(Shift.user_id == user_id, Shift.status.in_(OPEN_SHIFT_STATUSES)))


async def in_progress_visit_of(db: AsyncSession, user_id: int) -> Visit | None:
    return await db.scalar(select(Visit).where(Visit.user_id == user_id,
                                               Visit.status == VisitStatus.IN_PROGRESS.value))


async def own_shift(db: AsyncSession, user: Any, shift_uuid: uuid_lib.UUID) -> Shift:
    shift = await db.scalar(select(Shift).where(Shift.uuid == shift_uuid, Shift.user_id == user.id))
    if shift is None:
        raise FieldOpsNotFound(f"Shift {shift_uuid} not found")
    return shift


async def own_visit(db: AsyncSession, user: Any, visit_uuid: uuid_lib.UUID) -> Visit:
    visit = await db.scalar(select(Visit).where(Visit.uuid == visit_uuid, Visit.user_id == user.id))
    if visit is None:
        raise FieldOpsNotFound(f"Visit {visit_uuid} not found")
    return visit


def by_ref(model: Any, ref: str):
    """WHERE clause for a manager-facing ``{ref}``: uuid (preferred) or numeric id."""
    if str(ref).isdigit():
        return model.id == int(ref)
    try:
        return model.uuid == uuid_lib.UUID(str(ref))
    except ValueError:
        raise FieldOpsNotFound(f"'{ref}' is not a valid id") from None


def shift_brief(shift: Shift) -> dict:
    return {"uuid": str(shift.uuid), "status": shift.status, "started_at": shift.started_at.isoformat()
            if shift.started_at else None, "device_id": shift.device_id}


def visit_brief(visit: Visit) -> dict:
    return {"uuid": str(visit.uuid), "status": visit.status, "channel": visit.channel,
            "started_at": visit.started_at.isoformat() if visit.started_at else None}


__all__ = [
    "by_ref", "has_location_consent", "in_progress_visit_of", "media_exists", "open_shift_of", "org_timezone",
    "own_shift", "own_visit", "shift_brief", "visit_brief",
]
