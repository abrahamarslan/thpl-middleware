"""Devices, sessions and tracking-health events.

Registration happens on EVERY app launch (``POST /me/devices``): the installation is
upserted, the session row written, and the capability snapshot compared against what
continuous tracking needs — the response says what will break tracking (background
permission, approximate location, battery optimisation, a user-set clock), so the app can
guide the rep before the shift instead of discovering a gap after it.

Binding: a request's ``X-Device-Session`` resolves to its device. A shift is bound to the
device that started it; fixes and actions from another device are accepted and flagged
(``foreign_device``). A request without the header is a legacy/web client: allowed, unbound.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.modules.fieldops.clock import EventClock, SendContext, derive
from app.modules.fieldops.enums import (
    OPEN_SHIFT_STATUSES,
    TRACKING_LOSS_EVENTS,
    AnomalyType,
    DeviceEventType,
    Severity,
    SubjectType,
)
from app.modules.fieldops.errors import FieldOpsRuleError
from app.modules.fieldops.model import Device, DeviceEvent, DeviceSession, Shift
from app.modules.fieldops.schema import DeviceEventsIn, DeviceRegisterIn
from app.modules.fieldops.service import anomalies


def capability_warnings(session: DeviceSession) -> list[str]:
    """What in this session's snapshot will break continuous tracking."""
    warnings = []
    if session.location_permission and session.location_permission != "always":
        warnings.append("background_location_not_granted")
    if session.precise_location is False:
        warnings.append("approximate_location_only")
    if session.battery_optimization_exempt is False:
        warnings.append("battery_optimization_active")
    if session.auto_time_enabled is False:
        warnings.append("automatic_time_disabled")
    if session.is_rooted:
        warnings.append("device_rooted")
    return warnings


async def register(db: AsyncSession, user: Any, body: DeviceRegisterIn) -> tuple[Device, DeviceSession, list[str]]:
    now = dt.datetime.now(dt.UTC)
    device = await db.scalar(select(Device).where(Device.installation_id == body.installation_id))
    if device is None:
        device = Device(user_id=user.id, installation_id=body.installation_id, platform=body.platform.value,
                        organization_id=user.organization_id)
        db.add(device)
    elif device.user_id != user.id:
        # A shared handset changed hands: the installation follows whoever signs in on it.
        device.user_id = user.id
    device.manufacturer = body.manufacturer or device.manufacturer
    device.model = body.model or device.model
    device.os_version = body.os_version or device.os_version
    device.app_id = body.app_id or device.app_id
    device.push_token = body.push_token or device.push_token
    device.last_seen_at = now
    device.is_primary = True
    await db.flush()
    await db.execute(
        update(Device.__table__)
        .where(Device.__table__.c.tenant_id == device.tenant_id, Device.__table__.c.user_id == user.id,
               Device.__table__.c.id != device.id, Device.__table__.c.is_primary.is_(True))
        .values(is_primary=False)
    )

    fields = body.session.model_dump(exclude={"uuid"})
    fields["location_permission"] = (body.session.location_permission.value
                                     if body.session.location_permission else None)
    session = await db.scalar(select(DeviceSession).where(DeviceSession.uuid == body.session.uuid))
    if session is None:
        session = DeviceSession(uuid=body.session.uuid, device_id=device.id, user_id=user.id,
                                tenant_id=device.tenant_id, organization_id=device.organization_id, **fields)
        db.add(session)
    else:
        if session.user_id != user.id:
            raise FieldOpsRuleError("session_not_yours", "This session belongs to another user")
        for key, value in fields.items():
            if value is not None:
                setattr(session, key, value)
        session.last_seen_at = now
    await db.flush()
    return device, session, capability_warnings(session)


async def resolve_session(db: AsyncSession, user: Any, session_uuid: uuid_lib.UUID | None) -> DeviceSession | None:
    """The caller's session named by ``X-Device-Session``; None when no header (legacy/web client).

    An unknown or foreign session is refused: the header is a claim about identity, and a
    device must register before it can bind a shift.
    """
    if session_uuid is None:
        return None
    session = await db.scalar(select(DeviceSession).where(DeviceSession.uuid == session_uuid))
    if session is None or session.user_id != user.id:
        raise FieldOpsRuleError(
            "device_not_registered",
            "This device session is not registered; call POST /api/me/devices first",
            data={"session": str(session_uuid)},
        )
    return session


async def record_events(db: AsyncSession, user: Any, send: SendContext, body: DeviceEventsIn) -> tuple[int, int]:
    """Append tracking-health events; returns (accepted, duplicates). A tracking-loss event during an
    open shift opens a ``tracking_disabled`` anomaly; a mock-location app opens ``mock_location``."""
    known = {e.value for e in DeviceEventType}
    session = await resolve_session(db, user, send.session_uuid) if send.session_uuid else None
    rows = []
    for event in body.events:
        if event.event_type not in known:
            raise FieldOpsRuleError("unknown_event_type", f"Unknown device event type {event.event_type!r}",
                                    data={"allowed": sorted(known)})
        when = derive(send, EventClock(event.client_timestamp, event.elapsed_realtime_ms, event.boot_count))
        rows.append({
            "uuid": event.uuid, "tenant_id": user.tenant_id, "organization_id": user.organization_id,
            "user_id": user.id, "device_id": session.device_id if session else None,
            "session_uuid": send.session_uuid, "event_type": event.event_type,
            "client_timestamp": event.client_timestamp, "occurred_at": when.occurred_at,
            "received_at": send.received_at, "time_basis": when.basis, "details": event.details,
            "app_version": settings.VERSION, "app_metadata": {},
        })
    inserted = (await db.scalars(
        pg_insert(DeviceEvent).values(rows).on_conflict_do_nothing(index_elements=["uuid"])
        .returning(DeviceEvent.uuid)
    )).all()
    fresh = {u for u in inserted}

    shift = await db.scalar(select(Shift).where(Shift.user_id == user.id, Shift.status.in_(OPEN_SHIFT_STATUSES)))
    if shift is not None:
        for row in rows:
            if row["uuid"] not in fresh or row["occurred_at"] < (shift.started_at or row["occurred_at"]):
                continue
            if row["event_type"] in TRACKING_LOSS_EVENTS:
                await anomalies.open_anomaly(
                    db, anomaly_type=AnomalyType.TRACKING_DISABLED, severity=Severity.WARNING,
                    subject_type=SubjectType.SHIFT, subject=shift, user_id=user.id, shift_id=shift.id,
                    dedupe_key=f"tracking_disabled:shift:{shift.id}:{row['uuid']}", detector="device-events",
                    evidence={"event_type": row["event_type"], "occurred_at": row["occurred_at"].isoformat(),
                              "details": row["details"]},
                )
            elif row["event_type"] == DeviceEventType.MOCK_APP_DETECTED.value:
                await anomalies.open_anomaly(
                    db, anomaly_type=AnomalyType.MOCK_LOCATION, severity=Severity.CRITICAL,
                    subject_type=SubjectType.SHIFT, subject=shift, user_id=user.id, shift_id=shift.id,
                    dedupe_key=f"mock_location:shift:{shift.id}", detector="device-events",
                    evidence={"source": "mock_app_detected", "details": row["details"]},
                )
    return len(fresh), len(rows) - len(fresh)


__all__ = ["capability_warnings", "record_events", "register", "resolve_session"]
