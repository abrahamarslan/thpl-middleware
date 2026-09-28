"""THE location evaluator — the one place that turns a visit (or a shift start) plus the stream
into a verdict. Numbers come from ONE PostGIS query on ``geography`` (ellipsoidal, the
authority — never Python-side geodesy); their meaning comes from ``verification.py``.

Target resolution (nearest first)::

    geo.geofences on the place (active, valid at the instant)   polygon beats circle
    → the place's own coordinates, radius from its verification status (target_radius)
    → not_configured                                            (never blocks)

Evidence: every trusted fix of the user in [at − 120 s, at + 60 s] — the checkpoint fix sent
with the action is one of them — best accuracy first. Mock, impossible-hop and
duplicate-coordinate fixes are never evidence; neither is a manual location.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.enums import (
    UNTRUSTED_FLAGS,
    CheckAction,
    CheckPhase,
    CheckResult,
    Enforcement,
    SubjectType,
    TargetKind,
)
from app.modules.fieldops.model import LocationCheck, Visit
from app.modules.fieldops.service.policy import EffectivePolicy
from app.modules.fieldops.trackmath import dwell
from app.modules.fieldops.verification import (
    EVALUATOR_VERSION,
    Decision,
    classify,
    classify_polygon,
    decide,
    target_radius,
)

EVIDENCE_BEFORE = dt.timedelta(seconds=120)
EVIDENCE_AFTER = dt.timedelta(seconds=60)
DWELL_MARGIN = dt.timedelta(minutes=15)
DEFAULT_DWELL_S = 60


@dataclass(frozen=True, slots=True)
class Target:
    kind: TargetKind
    place_id: int | None = None
    geofence_id: int | None = None
    radius_m: float | None = None
    enforcement_override: str | None = None
    dwell_s: int = DEFAULT_DWELL_S
    place_verification: str | None = None

    @property
    def configured(self) -> bool:
        return self.kind is not TargetKind.NONE


@dataclass(frozen=True, slots=True)
class Verdict:
    result: CheckResult
    decision: Decision
    distance_m: float | None
    check: LocationCheck | None
    target: Target


async def resolve_target(db: AsyncSession, *, place_id: int | None, at: dt.datetime,
                         policy: EffectivePolicy) -> Target:
    if place_id is None:
        return Target(TargetKind.NONE)
    fence = (await db.execute(text("""
        SELECT id, (boundary IS NOT NULL) AS is_polygon, radius_m, visit_enforcement, dwell_threshold_s
          FROM geo.geofences
         WHERE place_id = :place AND status = 'active' AND deleted_at IS NULL
           AND deactivation_date IS NULL
           AND (valid_from IS NULL OR valid_from <= :at) AND (valid_to IS NULL OR valid_to > :at)
           AND (boundary IS NOT NULL OR (center IS NOT NULL AND radius_m IS NOT NULL))
         ORDER BY (boundary IS NOT NULL) DESC, id
         LIMIT 1
    """), {"place": place_id, "at": at})).first()
    if fence is not None:
        return Target(TargetKind.POLYGON if fence.is_polygon else TargetKind.CIRCLE, place_id=place_id,
                      geofence_id=fence.id, radius_m=None if fence.is_polygon else float(fence.radius_m),
                      enforcement_override=fence.visit_enforcement, dwell_s=int(fence.dwell_threshold_s or 0)
                      or DEFAULT_DWELL_S)
    place = (await db.execute(text(
        "SELECT (coordinates IS NOT NULL) AS has_point, verification_status FROM geo.places WHERE id = :place"
    ), {"place": place_id})).first()
    if place is None or not place.has_point:
        return Target(TargetKind.NONE, place_id=place_id)
    radius = target_radius(place.verification_status, base_m=policy.number("default_visit_radius_m"),
                           geocoded_factor=policy.number("geocoded_radius_factor"))
    if radius is None:
        return Target(TargetKind.NONE, place_id=place_id, place_verification=place.verification_status)
    return Target(TargetKind.PLACE_DEFAULT, place_id=place_id, radius_m=radius,
                  place_verification=place.verification_status)


def _measure_sql(target: Target) -> str:
    """A LATERAL subquery measuring ``p.coordinates`` against the target, as columns:

    ``distance_m`` (0 inside a polygon), ``covered`` and ``edge_m`` (polygon only: centre inside?
    distance to the boundary line).
    """
    if target.kind is TargetKind.POLYGON:
        return ("SELECT ST_Covers(g.boundary, p.coordinates) AS covered, "
                "ST_Distance(ST_Boundary(g.boundary::geometry)::geography, p.coordinates) AS edge_m, "
                "CASE WHEN ST_Covers(g.boundary, p.coordinates) THEN 0 "
                "ELSE ST_Distance(g.boundary, p.coordinates) END AS distance_m "
                "FROM geo.geofences g WHERE g.id = :fence")
    if target.kind is TargetKind.CIRCLE:
        return ("SELECT NULL::boolean AS covered, NULL::float8 AS edge_m, "
                "ST_Distance(g.center, p.coordinates) AS distance_m FROM geo.geofences g WHERE g.id = :fence")
    return ("SELECT NULL::boolean AS covered, NULL::float8 AS edge_m, "
            "ST_Distance(pl.coordinates, p.coordinates) AS distance_m FROM geo.places pl WHERE pl.id = :place")


_TRUSTED_FIXES = """
           p.coordinates IS NOT NULL AND NOT p.is_mock AND p.provider <> 'manual'
           AND (p.quality_flags & :untrusted) = 0
"""


async def _best_fix(db: AsyncSession, *, tenant_id: int, user_id: int, at: dt.datetime, target: Target):
    return (await db.execute(text(f"""
        SELECT p.uuid, p.recorded_at, p.accuracy_m, m.distance_m, m.covered, m.edge_m,
               count(*) OVER () AS evidence
          FROM fieldops.location_pings p
          LEFT JOIN LATERAL ({_measure_sql(target)}) m ON true
         WHERE p.tenant_id = :tenant AND p.user_id = :user
           AND p.occurred_at BETWEEN :lo AND :hi AND {_TRUSTED_FIXES}
         ORDER BY p.accuracy_m ASC NULLS LAST, abs(extract(epoch FROM p.occurred_at - :at))
         LIMIT 1
    """), {"tenant": tenant_id, "user": user_id, "lo": at - EVIDENCE_BEFORE, "hi": at + EVIDENCE_AFTER,
           "at": at, "untrusted": int(UNTRUSTED_FLAGS), "fence": target.geofence_id,
           "place": target.place_id})).first()


async def evaluate(
    db: AsyncSession,
    *,
    subject: Any,
    subject_type: SubjectType,
    phase: CheckPhase,
    user_id: int,
    at: dt.datetime,
    place_id: int | None,
    channel: str,
    policy: EffectivePolicy,
    offline: bool = False,
    justified: bool = False,
    enforce: bool = True,
) -> Verdict:
    """Verify ``subject`` at ``at`` and append a ``location_checks`` row. ``enforce=False`` records the
    verdict without applying the enforcement mode (visit END, shift start-place checks)."""
    target = await resolve_target(db, place_id=place_id, at=at, policy=policy)
    fix = None
    if channel == "field" and target.configured:
        fix = await _best_fix(db, tenant_id=subject.tenant_id, user_id=user_id, at=at, target=target)
    distance = float(fix.distance_m) if fix is not None and fix.distance_m is not None else None
    accuracy = float(fix.accuracy_m) if fix is not None and fix.accuracy_m is not None else None
    max_accuracy = policy.number("max_fix_accuracy_m")
    if target.kind is TargetKind.POLYGON:
        result = classify_polygon(fix.covered if fix is not None else None,
                                  float(fix.edge_m) if fix is not None and fix.edge_m is not None else None,
                                  accuracy, channel=channel, max_accuracy_m=max_accuracy)
    else:
        result = classify(distance, target.radius_m if target.configured else None, accuracy, channel=channel,
                          max_accuracy_m=max_accuracy)
    mode = Enforcement(target.enforcement_override or policy.geofence_enforcement)
    decision = decide(result, mode, offline=offline, justified=justified) if enforce \
        else Decision(CheckAction.RECORDED)
    check = LocationCheck(
        tenant_id=subject.tenant_id, organization_id=subject.organization_id, subject_type=subject_type.value,
        subject_id=subject.id, phase=phase.value, evaluator_version=EVALUATOR_VERSION, at=at,
        fix_uuid=fix.uuid if fix is not None else None, fix_recorded_at=fix.recorded_at if fix is not None else None,
        fix_accuracy_m=accuracy, evidence_count=int(fix.evidence) if fix is not None else 0,
        target_kind=target.kind.value, geofence_id=target.geofence_id, place_id=target.place_id,
        radius_m=target.radius_m, distance_m=distance, result=result.value, enforcement=mode.value,
        action_taken=decision.action.value,
        details={"place_verification": target.place_verification, "offline": offline} if target.place_verification
        or offline else None,
    )
    if decision.block_code is None:
        db.add(check)                  # a blocked start is refused, and its transaction rolled back
    return Verdict(result, decision, distance, check if decision.block_code is None else None, target)


async def detect_dwell(db: AsyncSession, visit: Visit, policy: EffectivePolicy) -> bool:
    """Set ``geofence_entry_at`` / ``geofence_exit_at`` / ``visit_time_basis`` from the stream.

    Uses fixes in [start − 15 min, end + 15 min]. KPIs use the geofence pair only when both exist
    with at least medium confidence; otherwise the button presses (``visit_time_basis = button``).
    Returns True when the visit changed.
    """
    if visit.channel != "field" or visit.started_at is None or visit.ended_at is None:
        return False
    target = await resolve_target(db, place_id=visit.place_id, at=visit.started_at, policy=policy)
    if not target.configured:
        changed = visit.visit_time_basis != "button"
        visit.visit_time_basis = "button"
        return changed
    rows = (await db.execute(text(f"""
        SELECT p.occurred_at, m.distance_m, m.covered, p.accuracy_m
          FROM fieldops.location_pings p
          LEFT JOIN LATERAL ({_measure_sql(target)}) m ON true
         WHERE p.tenant_id = :tenant AND p.user_id = :user
           AND p.occurred_at BETWEEN :lo AND :hi AND {_TRUSTED_FIXES}
           AND (p.accuracy_m IS NULL OR p.accuracy_m <= :max_acc)
         ORDER BY p.occurred_at
    """), {"tenant": visit.tenant_id, "user": visit.user_id, "lo": visit.started_at - DWELL_MARGIN,
           "hi": visit.ended_at + DWELL_MARGIN, "untrusted": int(UNTRUSTED_FLAGS),
           "max_acc": policy.number("max_fix_accuracy_m"), "fence": target.geofence_id,
           "place": target.place_id})).all()
    polygon = target.kind is TargetKind.POLYGON
    samples = [(r.occurred_at, bool(r.covered) if polygon else float(r.distance_m) <= float(target.radius_m or 0),
                r.accuracy_m) for r in rows if (r.covered is not None if polygon else r.distance_m is not None)]
    found = dwell(samples, dwell_s=target.dwell_s)
    before = (visit.geofence_entry_at, visit.geofence_exit_at, visit.visit_time_basis)
    visit.geofence_entry_at = found.entry_at
    visit.geofence_exit_at = found.exit_at
    usable = found.entry_at is not None and found.exit_at is not None and found.confidence in ("high", "medium")
    visit.visit_time_basis = "geofence" if usable else "button"
    return before != (visit.geofence_entry_at, visit.geofence_exit_at, visit.visit_time_basis)


__all__ = ["Target", "Verdict", "detect_dwell", "evaluate", "resolve_target"]
