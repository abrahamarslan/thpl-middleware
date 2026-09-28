"""The location stream's write path.

``ingest_batch`` — ``POST /api/me/location-pings`` (the offline queue's flush):

    0. a re-sent batch (same client uuid) is answered from ``ping_batches``         [1 query]
    1. each item is validated ON ITS OWN: a bad item is rejected, the rest go on
    2. shift / visit contexts are resolved from the client uuids in one query each   [≤2]
    3. per item (pure): business time (clock.py), the clamped partition key and the
       quality flags (accuracy, mock, impossible hop, skew, tampered clock, foreign
       device, out-of-order, stale replay, duplicate coordinates, during pause)
    4. clamped items only: a Redis first-seen guard (their key is not replay-stable)
    5. ``INSERT … ON CONFLICT DO NOTHING RETURNING uuid`` in chunks                 [1 per 200]
    6. ``user_live_locations`` ← the newest trusted fix, recency-guarded            [1]
    7. ``shifts.last_activity_at`` ← GREATEST(...) by Core UPDATE (no row_version)   [≤1]
    8. the batch row (counts + non-accepted results)                                  [1]

The query count does not grow with the batch (asserted by the N+1 test). Reverse geocoding,
metrics and dwell detection are deferred work, never on this path.

``write_checkpoint`` is the same row builder for a single labelled fix sent with a shift /
pause / visit / task action.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Any

import structlog
from geoalchemy2 import WKTElement
from pydantic import ValidationError
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.modules.fieldops import clock
from app.modules.fieldops.clock import Derived, EventClock, SendContext
from app.modules.fieldops.enums import (
    SHIFT_LABELS,
    VISIT_LABELS,
    LocationProvider,
    PingKind,
    QualityFlag,
    ShiftStatus,
)
from app.modules.fieldops.model import (
    DeviceSession,
    LocationPing,
    PingBatch,
    Shift,
    Visit,
)
from app.modules.fieldops.schema import (
    FixIn,
    ManualLocationIn,
    PingBatchIn,
    PingBatchResultOut,
    PingIn,
    PingItemResult,
)
from app.modules.fieldops.service.policy import EffectivePolicy, resolve_policy
from app.modules.fieldops.trackmath import Fix, is_impossible_hop, same_coordinates
from app.modules.users.model import UserLiveLocation

logger = structlog.get_logger("app.fieldops.ingest")

_CHUNK = 200
_REDIS_TTL_S = int(clock.MAX_BACKDATE.total_seconds())


@dataclass(slots=True)
class _Context:
    shift_id: int | None = None
    shift_device_id: int | None = None
    shift_status: str | None = None
    paused_since: dt.datetime | None = None
    visit_id: int | None = None


def point(latitude: float, longitude: float) -> WKTElement:
    """WGS84 point — longitude FIRST (PostGIS order), the one place this module builds one."""
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def _flags(
    *, fix: FixIn, derived: Derived, clamped: bool, previous: Fix | None, policy: EffectivePolicy,
    session: DeviceSession | None, device_id: int | None, ctx: _Context, last_sequence: int | None,
    received_at: dt.datetime,
) -> tuple[int, Fix]:
    current = Fix(derived.occurred_at, fix.latitude, fix.longitude, fix.accuracy_m, fix.speed_mps, 0,
                  fix.activity_type.value if fix.activity_type else None, fix.activity_confidence, fix.is_mock)
    bits = QualityFlag.NONE
    if fix.accuracy_m is not None and fix.accuracy_m > policy.number("max_fix_accuracy_m"):
        bits |= QualityFlag.LOW_ACCURACY
    if fix.is_mock:
        bits |= QualityFlag.MOCK
    if is_impossible_hop(previous, current):
        bits |= QualityFlag.IMPOSSIBLE_SPEED
    if derived.clock_skew_ms is not None and abs(derived.clock_skew_ms) > policy.number("clock_skew_flag_seconds") * 1000:
        bits |= QualityFlag.CLOCK_SKEW
    if session is not None and session.auto_time_enabled is False:
        bits |= QualityFlag.CLOCK_TAMPERED
    if clamped:
        bits |= QualityFlag.PARTITION_KEY_CLAMPED
    if ctx.shift_device_id is not None and device_id is not None and ctx.shift_device_id != device_id:
        bits |= QualityFlag.FOREIGN_DEVICE
    if last_sequence is not None and fix.sequence_no is not None and fix.sequence_no <= last_sequence:
        bits |= QualityFlag.OUT_OF_ORDER
    if received_at - derived.occurred_at > clock.STALE_AFTER:
        bits |= QualityFlag.STALE_REPLAY
    if same_coordinates(previous, current):
        bits |= QualityFlag.DUPLICATE_COORDINATES
    if ctx.shift_status == ShiftStatus.PAUSED.value and ctx.paused_since and derived.occurred_at >= ctx.paused_since:
        bits |= QualityFlag.DURING_PAUSE
    return int(bits), Fix(current.occurred_at, current.latitude, current.longitude, current.accuracy_m,
                          current.speed_mps, int(bits), current.activity_type, current.activity_confidence,
                          current.is_mock)


def build_row(
    *, user: Any, fix: FixIn, derived: Derived, recorded_at: dt.datetime, received_at: dt.datetime,
    kind: str, label: str | None, shift_uuid: uuid_lib.UUID | None, visit_uuid: uuid_lib.UUID | None,
    ctx: _Context, device_id: int | None, session_uuid: uuid_lib.UUID | None, flags: int,
    manual_reason: str | None = None, batch_id: int | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": user.tenant_id, "organization_id": user.organization_id, "user_id": user.id,
        "recorded_at": recorded_at, "uuid": fix.uuid, "batch_id": batch_id, "device_id": device_id,
        "device_session_uuid": session_uuid, "shift_id": ctx.shift_id, "visit_id": ctx.visit_id,
        "shift_uuid": shift_uuid, "visit_uuid": visit_uuid, "kind": kind, "checkpoint_label": label,
        "client_timestamp": fix.client_timestamp, "elapsed_realtime_ms": fix.elapsed_realtime_ms,
        "boot_count": fix.boot_count, "sequence_no": fix.sequence_no, "received_at": received_at,
        "occurred_at": derived.occurred_at, "time_basis": derived.basis, "clock_skew_ms": derived.clock_skew_ms,
        "coordinates": point(fix.latitude, fix.longitude), "accuracy_m": fix.accuracy_m,
        "altitude_m": fix.altitude_m, "vertical_accuracy_m": fix.vertical_accuracy_m,
        "heading_deg": fix.heading_deg, "heading_accuracy_deg": fix.heading_accuracy_deg,
        "speed_mps": fix.speed_mps, "speed_accuracy_mps": fix.speed_accuracy_mps, "provider": fix.provider.value,
        "satellites": fix.satellites, "is_mock": fix.is_mock,
        "activity_type": fix.activity_type.value if fix.activity_type else None,
        "activity_confidence": fix.activity_confidence, "battery_pct": fix.battery_pct,
        "is_charging": fix.is_charging, "power_save": fix.power_save, "network_type": fix.network_type,
        "quality_flags": flags, "manual_reason": manual_reason, "extras": fix.extras,
        "app_version": settings.VERSION, "app_metadata": {},
    }


async def _contexts(db: AsyncSession, user: Any, shift_uuids: set, visit_uuids: set) -> tuple[dict, dict]:
    shifts: dict[uuid_lib.UUID, Shift] = {}
    visits: dict[uuid_lib.UUID, Visit] = {}
    if shift_uuids:
        rows = (await db.scalars(select(Shift).where(Shift.uuid.in_(shift_uuids), Shift.user_id == user.id))).all()
        shifts = {r.uuid: r for r in rows}
    if visit_uuids:
        rows = (await db.scalars(select(Visit).where(Visit.uuid.in_(visit_uuids)))).all()
        visits = {r.uuid: r for r in rows}
    return shifts, visits


def _context_for(item: PingIn, shifts: dict, visits: dict) -> _Context:
    ctx = _Context()
    visit = visits.get(item.visit_uuid) if item.visit_uuid else None
    shift = shifts.get(item.shift_uuid) if item.shift_uuid else None
    if visit is not None:
        ctx.visit_id = visit.id
        if shift is None and visit.shift_id is not None:
            ctx.shift_id = visit.shift_id
    if shift is not None:
        ctx.shift_id = shift.id
        ctx.shift_device_id = shift.device_id
        ctx.shift_status = shift.status
        ctx.paused_since = shift.paused_since
    return ctx


async def _first_seen(tenant_id: int, uuids: list[uuid_lib.UUID]) -> set[uuid_lib.UUID]:
    """Redis guard for clamped items. Fails OPEN: without Redis the DB index still dedupes most replays."""
    if not uuids:
        return set()
    try:
        from app.database.redis import redis_client

        pipe = redis_client.pipeline()
        for u in uuids:
            pipe.set(f"fieldops:ping:{tenant_id}:{u}", "1", nx=True, ex=_REDIS_TTL_S)
        results = await pipe.execute()
        return {u for u, ok in zip(uuids, results, strict=True) if ok}
    except Exception as exc:  # noqa: BLE001 — availability over a rare duplicate
        logger.warning("fieldops.ingest.redis_guard_unavailable", error=str(exc)[:200])
        return set(uuids)


async def _previous_fix(db: AsyncSession, user: Any) -> Fix | None:
    """The last known position — the reference for the first item's impossible-hop check."""
    row = (await db.execute(text(
        "SELECT ST_Y(coordinates::geometry), ST_X(coordinates::geometry), recorded_at, accuracy_m "
        "FROM user_live_locations WHERE tenant_id = :t AND user_id = :u AND coordinates IS NOT NULL"
    ), {"t": user.tenant_id, "u": user.id})).first()
    if row is None or row[2] is None:
        return None
    return Fix(row[2], row[0], row[1], row[3])


async def update_live(db: AsyncSession, user: Any, row: dict[str, Any], *, tracking_active: bool) -> None:
    """Project the newest trusted fix onto ``user_live_locations`` — never backwards in time.

    ``recorded_at`` there holds the fix's corrected business time (occurred_at): an offline replay of
    yesterday's fixes must not overwrite where the rep is now.
    """
    values = {
        "tenant_id": user.tenant_id, "organization_id": user.organization_id, "user_id": user.id,
        "coordinates": row["coordinates"], "accuracy_m": row["accuracy_m"], "altitude_m": row["altitude_m"],
        "heading_deg": row["heading_deg"], "speed_mps": row["speed_mps"], "location_source": row["provider"],
        "is_moving": None, "tracking_active": tracking_active, "network_type": row["network_type"],
        "recorded_at": row["occurred_at"], "app_version": settings.VERSION,
    }
    stmt = pg_insert(UserLiveLocation).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserLiveLocation.tenant_id, UserLiveLocation.user_id],
        set_={key: stmt.excluded[key] for key in values if key not in ("tenant_id", "user_id")}
        | {"received_at": func.now(), "updated_at": func.now()},
        where=or_(UserLiveLocation.recorded_at.is_(None), stmt.excluded.recorded_at > UserLiveLocation.recorded_at),
    )
    await db.execute(stmt)


async def touch_shifts(db: AsyncSession, latest: dict[int, dt.datetime]) -> None:
    """``last_activity_at = GREATEST(...)`` — Core UPDATE, no row_version bump, so ingest never collides
    with a manager editing the shift."""
    table = Shift.__table__
    for shift_id, moment in latest.items():
        await db.execute(
            update(table).where(table.c.id == shift_id)
            .values(last_activity_at=func.greatest(func.coalesce(table.c.last_activity_at, moment), moment))
        )


async def ingest_batch(db: AsyncSession, user: Any, send: SendContext, body: PingBatchIn,
                       *, session: DeviceSession | None) -> PingBatchResultOut:
    started = time.monotonic()
    existing = await db.scalar(select(PingBatch).where(PingBatch.uuid == body.uuid))
    if existing is not None:
        if existing.user_id != user.id:
            from app.modules.fieldops.errors import FieldOpsConflict

            raise FieldOpsConflict("batch_uuid_conflict", "This batch uuid belongs to another user")
        return PingBatchResultOut(
            batch_uuid=existing.uuid, accepted=existing.accepted_count, duplicates=existing.duplicate_count,
            rejected=existing.rejected_count, results=[PingItemResult(**r) for r in existing.results],
            replayed=True,
        )

    received = clock.utc(send.received_at)
    results: list[PingItemResult] = []
    items: list[PingIn] = []
    for raw in body.pings:
        try:
            item = PingIn.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            results.append(PingItemResult(uuid=str(raw.get("uuid")) if isinstance(raw, dict) else None,
                                          status="rejected",
                                          reason=f"{'.'.join(str(p) for p in first.get('loc', ()))}: {first.get('msg')}"))
            continue
        if item.checkpoint_label and item.checkpoint_label in VISIT_LABELS and item.visit_uuid is None:
            results.append(PingItemResult(uuid=str(item.uuid), status="rejected", reason="visit label needs visit_uuid"))
            continue
        if item.checkpoint_label and item.checkpoint_label in SHIFT_LABELS and item.shift_uuid is None:
            results.append(PingItemResult(uuid=str(item.uuid), status="rejected", reason="shift label needs shift_uuid"))
            continue
        items.append(item)

    policy = await resolve_policy(db, user)
    shifts, visits = await _contexts(db, user, {i.shift_uuid for i in items if i.shift_uuid},
                                     {i.visit_uuid for i in items if i.visit_uuid})
    device_id = session.device_id if session else None

    prepared: list[tuple[PingIn, dict[str, Any], bool]] = []
    derived_items = []
    for item in items:
        derived = clock.derive(send, EventClock(item.client_timestamp, item.elapsed_realtime_ms, item.boot_count))
        derived_items.append((derived.occurred_at, item, derived))
    derived_items.sort(key=lambda t: t[0])

    previous = await _previous_fix(db, user)
    last_sequence: int | None = None
    for _, item, derived in derived_items:
        recorded_at, clamped = clock.partition_key(item.client_timestamp, received)
        ctx = _context_for(item, shifts, visits)
        flags, as_fix = _flags(fix=item, derived=derived, clamped=clamped, previous=previous, policy=policy,
                               session=session, device_id=device_id, ctx=ctx, last_sequence=last_sequence,
                               received_at=received)
        if item.sequence_no is not None:
            last_sequence = max(last_sequence or 0, item.sequence_no)
        if not (flags & (QualityFlag.MOCK | QualityFlag.IMPOSSIBLE_SPEED)):
            previous = as_fix
        kind = item.kind if item.provider is not LocationProvider.MANUAL else PingKind.MANUAL.value
        row = build_row(user=user, fix=item, derived=derived, recorded_at=recorded_at, received_at=received,
                        kind=kind, label=item.checkpoint_label, shift_uuid=item.shift_uuid,
                        visit_uuid=item.visit_uuid, ctx=ctx, device_id=device_id,
                        session_uuid=send.session_uuid, flags=flags, manual_reason=item.manual_reason)
        prepared.append((item, row, clamped))

    fresh_clamped = await _first_seen(user.tenant_id, [i.uuid for i, _, c in prepared if c])
    to_insert = [(i, r) for i, r, c in prepared if not c or i.uuid in fresh_clamped]
    duplicates = [i for i, _, c in prepared if c and i.uuid not in fresh_clamped]

    accepted: set[uuid_lib.UUID] = set()
    for start in range(0, len(to_insert), _CHUNK):
        chunk = [r for _, r in to_insert[start:start + _CHUNK]]
        returned = (await db.scalars(
            pg_insert(LocationPing).values(chunk)
            .on_conflict_do_nothing(constraint="uq_location_pings_client")
            .returning(LocationPing.uuid)
        )).all()
        accepted.update(returned)
    duplicates += [i for i, _ in to_insert if i.uuid not in accepted]
    results += [PingItemResult(uuid=str(i.uuid), status="duplicate") for i in duplicates]

    fresh_rows = [r for i, r in to_insert if i.uuid in accepted]
    trusted = [r for r in fresh_rows if not r["is_mock"]
               and not r["quality_flags"] & int(QualityFlag.IMPOSSIBLE_SPEED | QualityFlag.LOW_ACCURACY)]
    if trusted:
        newest = max(trusted, key=lambda r: r["occurred_at"])
        open_shift = any(s.status in (ShiftStatus.ACTIVE.value, ShiftStatus.PAUSED.value) for s in shifts.values())
        await update_live(db, user, newest, tracking_active=open_shift)
    latest: dict[int, dt.datetime] = {}
    for r in fresh_rows:
        if r["shift_id"] is not None:
            latest[r["shift_id"]] = max(latest.get(r["shift_id"], r["occurred_at"]), r["occurred_at"])
    await touch_shifts(db, latest)

    rejected = sum(1 for r in results if r.status == "rejected")
    batch = PingBatch(
        uuid=body.uuid, tenant_id=user.tenant_id, organization_id=user.organization_id, user_id=user.id,
        device_id=device_id, device_session_uuid=send.session_uuid, client_timestamp=send.sent_at,
        client_elapsed_ms=send.sent_elapsed_ms, client_boot_count=send.boot_count, received_at=received,
        item_count=len(body.pings), accepted_count=len(accepted), duplicate_count=len(duplicates),
        rejected_count=rejected, results=[r.model_dump() for r in results],
        payload_sha256=hashlib.sha256(json.dumps(body.pings, sort_keys=True, default=str).encode()).hexdigest(),
        ingest_ms=int((time.monotonic() - started) * 1000),
    )
    db.add(batch)
    await db.flush()
    logger.info("fieldops.ingest.batch", user_id=user.id, items=len(body.pings), accepted=len(accepted),
                duplicates=len(duplicates), rejected=rejected, ingest_ms=batch.ingest_ms)
    return PingBatchResultOut(batch_uuid=body.uuid, accepted=len(accepted), duplicates=len(duplicates),
                              rejected=rejected, results=results)


async def write_checkpoint(
    db: AsyncSession, *, user: Any, send: SendContext, derived: Derived, label: str,
    fix: FixIn | None, manual: ManualLocationIn | None, shift: Shift | None = None,
    visit: Visit | None = None, device_id: int | None = None, policy: EffectivePolicy | None = None,
) -> bool:
    """Write the labelled fix of an action into the stream (idempotent on the fix uuid).

    A manual location with coordinates becomes a ``manual`` row (provider manual + reason) — recorded,
    never evidence. No fix and no manual coordinates → nothing to record (returns False).
    """
    if fix is None and (manual is None or manual.latitude is None or manual.longitude is None):
        return False
    if fix is None:
        fix = FixIn(uuid=uuid_lib.uuid4(), latitude=manual.latitude, longitude=manual.longitude,
                    provider=LocationProvider.MANUAL)
    received = clock.utc(send.received_at)
    fix_derived = clock.derive(send, EventClock(fix.client_timestamp, fix.elapsed_realtime_ms, fix.boot_count)) \
        if (fix.client_timestamp or fix.elapsed_realtime_ms is not None) else derived
    recorded_at, _clamped = clock.partition_key(fix.client_timestamp or derived.occurred_at, received)
    ctx = _Context(
        shift_id=shift.id if shift is not None else (visit.shift_id if visit is not None else None),
        shift_device_id=shift.device_id if shift is not None else None,
        shift_status=shift.status if shift is not None else None,
        paused_since=shift.paused_since if shift is not None else None,
        visit_id=visit.id if visit is not None else None,
    )
    policy = policy or await resolve_policy(db, user)
    flags, _ = _flags(fix=fix, derived=fix_derived, clamped=_clamped, previous=None, policy=policy, session=None,
                      device_id=device_id, ctx=ctx, last_sequence=None, received_at=received)
    manual_reason = manual.reason if (manual is not None and fix.provider is LocationProvider.MANUAL) else None
    if fix.provider is LocationProvider.MANUAL and manual_reason is None:
        manual_reason = "manual location"
    shift_uuid = shift.uuid if shift is not None else None
    if shift_uuid is None and visit is not None and visit.shift_id is not None:
        shift_uuid = await db.scalar(select(Shift.uuid).where(Shift.id == visit.shift_id))
    row = build_row(user=user, fix=fix, derived=fix_derived, recorded_at=recorded_at, received_at=received,
                    kind=PingKind.CHECKPOINT.value, label=label, shift_uuid=shift_uuid,
                    visit_uuid=visit.uuid if visit is not None else None, ctx=ctx, device_id=device_id,
                    session_uuid=send.session_uuid, flags=flags, manual_reason=manual_reason)
    inserted = await db.scalar(
        pg_insert(LocationPing).values(row).on_conflict_do_nothing(constraint="uq_location_pings_client")
        .returning(LocationPing.uuid)
    )
    if inserted is not None and not fix.is_mock and fix.provider is not LocationProvider.MANUAL:
        await update_live(db, user, row, tracking_active=shift is not None and shift.is_open)
    if inserted is not None and ctx.shift_id is not None:
        await touch_shifts(db, {ctx.shift_id: row["occurred_at"]})
    return inserted is not None


async def link_orphan_pings(db: AsyncSession) -> int:
    """Back-fill ``shift_id`` / ``visit_id`` of fixes that arrived before their entity (offline queues
    do not guarantee order). Serves ``ix_location_pings_unlinked``. Returns rows linked."""
    table = LocationPing.__table__
    shifts = Shift.__table__
    visits = Visit.__table__
    linked = 0
    result = await db.execute(
        update(table)
        .where(table.c.shift_uuid == shifts.c.uuid, table.c.shift_id.is_(None), table.c.tenant_id == shifts.c.tenant_id)
        .values(shift_id=shifts.c.id)
    )
    linked += result.rowcount or 0
    result = await db.execute(
        update(table)
        .where(table.c.visit_uuid == visits.c.uuid, table.c.visit_id.is_(None), table.c.tenant_id == visits.c.tenant_id)
        .values(visit_id=visits.c.id, shift_id=func.coalesce(table.c.shift_id, visits.c.shift_id))
    )
    linked += result.rowcount or 0
    return linked


__all__ = ["build_row", "ingest_batch", "link_orphan_pings", "point", "touch_shifts", "update_live",
           "write_checkpoint"]
