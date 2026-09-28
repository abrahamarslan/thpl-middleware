"""Shift metrics — derived, recomputable KPIs, and the anomaly detectors that read them.

Two durations, never conflated:

* ``paid_minutes``     wall clock minus unpaid pauses — attendance / payroll;
* ``engaged_minutes``  visit time + travel between the first and the last visit — productivity.

Visit time uses the geofence-verified bounds when dwell detection produced confident ones
(``visit_time_basis = geofence``), the button presses otherwise. Tracking coverage is measured
over the TRACKED time: pauses during which the app was told to stop tracking are excluded, so
a lunch break is not a "gap".

Field and telephonic/video figures are separate columns: phone orders must not inflate field
coverage. ``geofence_compliance_pct`` has the visits that HAD a target as its denominator — an
organization with no fences gets NULL, never 0 %.

Recompute any time (after a correction, after late pings): the row is upserted and the write is
skipped when nothing changed. ``METRICS_VERSION`` goes on every row; bump it when an algorithm
below changes and recompute history.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections import Counter
from decimal import Decimal

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.enums import (
    AnomalyType,
    Channel,
    CheckResult,
    QualityFlag,
    Severity,
    SubjectType,
    TaskStatus,
    TrackingMode,
    VisitOutcome,
    VisitStatus,
)
from app.modules.fieldops.model import Shift, ShiftMetrics, ShiftPause, Visit, VisitTask
from app.modules.fieldops.service import anomalies
from app.modules.fieldops.service.shifts import policy_of
from app.modules.fieldops.task_types import REGISTRY
from app.modules.fieldops.trackmath import (
    Fix,
    accepted,
    clip,
    coverage,
    distance_km,
    merge,
    minutes,
    moving_intervals,
    subtract,
)

logger = structlog.get_logger("app.fieldops.metrics")

METRICS_VERSION = 1
_CHECKED = (CheckResult.INSIDE.value, CheckResult.OUTSIDE.value, CheckResult.UNCERTAIN.value,
            CheckResult.NO_FIX.value)


def _dec(value: float | None, places: int = 2) -> Decimal | None:
    return None if value is None else Decimal(str(round(value, places)))


async def _fixes(db: AsyncSession, shift: Shift, start: dt.datetime, end: dt.datetime) -> list[tuple]:
    return (await db.execute(text("""
        SELECT occurred_at, ST_Y(coordinates::geometry) AS lat, ST_X(coordinates::geometry) AS lng, accuracy_m,
               speed_mps, quality_flags, activity_type, activity_confidence, is_mock, clock_skew_ms, provider
          FROM fieldops.location_pings
         WHERE tenant_id = :tenant AND user_id = :user AND occurred_at BETWEEN :start AND :end
           AND coordinates IS NOT NULL
         ORDER BY occurred_at
    """), {"tenant": shift.tenant_id, "user": shift.user_id, "start": start, "end": end})).all()


async def compute_shift_metrics(db: AsyncSession, shift_id: int) -> ShiftMetrics | None:
    shift = await db.scalar(select(Shift).where(Shift.id == shift_id).execution_options(all_tenants=True))
    if shift is None or shift.started_at is None:
        return None
    policy = policy_of(shift)
    end = shift.ended_at or dt.datetime.now(dt.UTC)
    window = (shift.started_at, max(end, shift.started_at))

    pauses = (await db.scalars(select(ShiftPause).where(ShiftPause.shift_id == shift.id))).all()
    pause_iv = [(p.started_at, p.ended_at or end) for p in pauses]
    unpaid_iv = [(p.started_at, p.ended_at or end) for p in pauses if not p.is_paid]
    suspended_iv = [(p.started_at, p.ended_at or end) for p in pauses if p.tracking_suspended]
    wall = minutes([window])
    pause_min = minutes(clip(pause_iv, window))
    paid = wall - minutes(clip(unpaid_iv, window))

    rows = await _fixes(db, shift, *window)
    max_accuracy = policy.number("max_fix_accuracy_m")
    fixes = [Fix(r.occurred_at, r.lat, r.lng, r.accuracy_m, r.speed_mps, r.quality_flags or 0, r.activity_type,
                 r.activity_confidence, r.is_mock) for r in rows if r.provider != "manual"]
    good = accepted(fixes, max_accuracy_m=max_accuracy)
    skews = [abs(r.clock_skew_ms) for r in rows if r.clock_skew_ms is not None]

    visits = (await db.scalars(select(Visit).where(Visit.shift_id == shift.id))).all()
    field_visits = [v for v in visits if v.channel == Channel.FIELD.value]
    visit_iv = []
    for v in visits:
        if v.channel != Channel.FIELD.value or v.started_at is None:
            continue
        if v.visit_time_basis == "geofence" and v.geofence_entry_at and v.geofence_exit_at:
            visit_iv.append((v.geofence_entry_at, v.geofence_exit_at))
        elif v.ended_at is not None:
            visit_iv.append((v.started_at, v.ended_at))
    visit_iv = merge(clip(visit_iv, window))
    visit_min = minutes(visit_iv)

    interval = dt.timedelta(seconds=max(int(policy.ping_interval_s), 1))
    stationary = dt.timedelta(seconds=max(int(policy.stationary_interval_s), 1))
    moving = moving_intervals(good, max_gap=max(stationary * 2, dt.timedelta(minutes=10)))
    travel_iv = subtract(clip(moving, window), visit_iv + pause_iv)
    travel_min = minutes(travel_iv)
    started_visits = sorted((v for v in field_visits if v.started_at), key=lambda v: v.started_at)
    first_visit = started_visits[0].started_at if started_visits else None
    last_visit = max((v.ended_at for v in started_visits if v.ended_at), default=None)
    engaged = visit_min
    if first_visit and last_visit and last_visit > first_visit:
        engaged += minutes(clip(travel_iv, (first_visit, last_visit)))
    idle = max(wall - pause_min - visit_min - travel_min, 0.0)

    tracked = subtract([window], suspended_iv)
    coverage_pct, longest_gap = coverage([f.occurred_at for f in good], tracked, bucket=max(interval * 2, stationary))

    visit_ids = [v.id for v in visits]
    tasks = (await db.scalars(select(VisitTask).where(VisitTask.visit_id.in_(visit_ids),
                                                      VisitTask.status == TaskStatus.SUBMITTED.value))
             ).all() if visit_ids else []
    channel_of = {v.id: v.channel for v in visits}
    currencies = Counter(t.currency_code for t in tasks if t.amount is not None and t.currency_code)
    currency = currencies.most_common(1)[0][0] if currencies else None
    orders_field = orders_tel = 0
    value_field = value_tel = collections = Decimal(0)
    for t in tasks:
        spec = REGISTRY.get(t.task_type)
        if spec is None:
            continue
        same_currency = t.amount is not None and t.currency_code == currency
        if spec.is_order:
            if channel_of.get(t.visit_id) == Channel.FIELD.value:
                orders_field += 1
                value_field += t.amount if same_currency else Decimal(0)
            else:
                orders_tel += 1
                value_tel += t.amount if same_currency else Decimal(0)
        if spec.is_collection and same_currency:
            collections += t.amount

    checked = [v for v in field_visits if v.start_check in _CHECKED]
    inside = sum(1 for v in checked if v.start_check == CheckResult.INSIDE.value)
    values = {
        "wall_clock_minutes": _dec(wall), "pause_minutes": _dec(pause_min), "paid_minutes": _dec(paid),
        "engaged_minutes": _dec(engaged), "visit_minutes": _dec(visit_min), "travel_minutes": _dec(travel_min),
        "idle_minutes": _dec(idle), "first_visit_at": first_visit, "last_visit_at": last_visit,
        "fix_count": len(fixes), "accepted_fix_count": len(good),
        "tracking_coverage_pct": _dec(coverage_pct) if policy.tracking_mode == TrackingMode.CONTINUOUS.value else None,
        "longest_gap_minutes": _dec(longest_gap), "mock_fix_count": sum(1 for f in fixes if f.is_mock),
        "low_accuracy_fix_count": sum(1 for f in fixes if f.flags & int(QualityFlag.LOW_ACCURACY)),
        "clock_skew_max_s": int(max(skews) / 1000) if skews else None,
        "gps_distance_km": _dec(distance_km(good), 3),
        "odometer_distance_km": (shift.odometer_end_km - shift.odometer_start_km)
        if shift.odometer_end_km is not None and shift.odometer_start_km is not None else None,
        "visits_total": len(visits),
        "visits_completed": sum(1 for v in visits if v.status == VisitStatus.COMPLETED.value),
        "visits_cancelled": sum(1 for v in visits if v.status == VisitStatus.CANCELLED.value),
        "visits_planned": sum(1 for v in visits if v.source == "planned"),
        "visits_unplanned": sum(1 for v in visits if v.source != "planned"),
        "field_visits": len(field_visits),
        "telephonic_visits": sum(1 for v in visits if v.channel == Channel.TELEPHONIC.value),
        "video_visits": sum(1 for v in visits if v.channel == Channel.VIDEO.value),
        "productive_visits": sum(1 for v in visits if v.outcome == VisitOutcome.ORDER_TAKEN.value),
        "visits_checked": len(checked), "visits_inside": inside,
        "visits_outside": sum(1 for v in checked if v.start_check == CheckResult.OUTSIDE.value),
        "visits_uncertain": sum(1 for v in checked if v.start_check == CheckResult.UNCERTAIN.value),
        "geofence_compliance_pct": _dec(100.0 * inside / len(checked)) if checked else None,
        "orders_field": orders_field, "orders_telephonic": orders_tel, "order_value_field": value_field,
        "order_value_telephonic": value_tel, "collections_value": collections, "currency_code": currency,
    }
    await _detect(db, shift, policy, values, fixes, wall)
    values["anomaly_count_open"] = await anomalies.count_open(db, shift_id=shift.id)

    digest = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    metrics = await db.scalar(select(ShiftMetrics).where(ShiftMetrics.shift_id == shift.id)
                              .execution_options(all_tenants=True))
    if metrics is not None and metrics.inputs_hash == digest and metrics.metrics_version == METRICS_VERSION:
        return metrics
    if metrics is None:
        metrics = ShiftMetrics(shift_id=shift.id, tenant_id=shift.tenant_id, organization_id=shift.organization_id,
                               metrics_version=METRICS_VERSION)
        db.add(metrics)
    for key, value in values.items():
        setattr(metrics, key, value)
    metrics.metrics_version = METRICS_VERSION
    metrics.inputs_hash = digest
    metrics.computed_at = dt.datetime.now(dt.UTC)
    await db.flush()
    logger.info("fieldops.metrics_computed", shift_id=shift.id, paid=str(values["paid_minutes"]),
                engaged=str(values["engaged_minutes"]), coverage=str(values["tracking_coverage_pct"]))
    return metrics


async def _detect(db: AsyncSession, shift: Shift, policy, values: dict, fixes: list[Fix], wall: float) -> None:
    """Anomalies that only the whole shift reveals. Idempotent (dedupe keys)."""

    async def raise_(kind: AnomalyType, severity: Severity, evidence: dict) -> None:
        await anomalies.open_anomaly(db, anomaly_type=kind, severity=severity, subject_type=SubjectType.SHIFT,
                                     subject=shift, user_id=shift.user_id, shift_id=shift.id,
                                     dedupe_key=f"{kind.value}:shift:{shift.id}", detector="metrics",
                                     evidence=evidence)

    if shift.is_open:
        return                                   # judge a shift once it is over
    continuous = policy.tracking_mode == TrackingMode.CONTINUOUS.value
    gap = values["longest_gap_minutes"]
    if continuous and gap is not None and float(gap) > int(policy.gap_flag_minutes):
        await raise_(AnomalyType.LONG_GAP, Severity.WARNING,
                     {"longest_gap_minutes": float(gap), "threshold": policy.gap_flag_minutes})
    coverage_pct = values["tracking_coverage_pct"]
    if continuous and coverage_pct is not None and wall >= 30 \
            and float(coverage_pct) < policy.number("min_tracking_coverage_pct"):
        await raise_(AnomalyType.LOW_TRACKING_COVERAGE, Severity.WARNING,
                     {"coverage_pct": float(coverage_pct), "threshold": float(policy.min_tracking_coverage_pct)})
    if values["mock_fix_count"] >= 3:
        await raise_(AnomalyType.MOCK_LOCATION, Severity.CRITICAL, {"mock_fixes": values["mock_fix_count"]})
    impossible = sum(1 for f in fixes if f.flags & int(QualityFlag.IMPOSSIBLE_SPEED))
    if impossible >= 3:
        await raise_(AnomalyType.IMPOSSIBLE_SPEED, Severity.WARNING, {"fixes": impossible})
    skew = values["clock_skew_max_s"]
    if skew is not None and skew > int(policy.clock_skew_flag_seconds):
        await raise_(AnomalyType.CLOCK_SKEW, Severity.WARNING, {"max_skew_s": skew})
    if any(f.flags & int(QualityFlag.CLOCK_TAMPERED) for f in fixes):
        await raise_(AnomalyType.CLOCK_TAMPERED, Severity.WARNING, {"source": "automatic time disabled"})
    foreign = sum(1 for f in fixes if f.flags & int(QualityFlag.FOREIGN_DEVICE))
    if foreign:
        await raise_(AnomalyType.FOREIGN_DEVICE, Severity.WARNING, {"fixes": foreign})


async def shifts_needing_metrics(db: AsyncSession, *, since: dt.datetime, limit: int = 500) -> list[int]:
    """Closed shifts with no metrics, or with fixes/tasks newer than their metrics (late data)."""
    return list((await db.execute(text("""
        SELECT s.id FROM fieldops.shifts s
          LEFT JOIN fieldops.shift_metrics m ON m.shift_id = s.id
         WHERE s.status IN ('completed','auto_closed') AND s.deleted_at IS NULL AND s.ended_at >= :since
           AND (m.id IS NULL OR m.metrics_version < :version OR s.updated_at > m.computed_at
                OR EXISTS (SELECT 1 FROM fieldops.location_pings p
                            WHERE p.shift_id = s.id AND p.received_at > m.computed_at))
         ORDER BY s.ended_at
         LIMIT :limit
    """), {"since": since, "version": METRICS_VERSION, "limit": limit})).scalars().all())


__all__ = ["METRICS_VERSION", "compute_shift_metrics", "shifts_needing_metrics"]
