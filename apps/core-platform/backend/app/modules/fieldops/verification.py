"""Location verification rules — PURE, table-tested. The spatial query is in
``service/verify.py``; these functions decide what its numbers MEAN.

Why not "latest ping inside the radius → inside, else outside" (improvement-document §6):
accuracy is ignored (a fix 90 m out with ±150 m accuracy is not evidence of being
outside), one sample is used (possibly minutes old, or a cold-start fix), and everything
uncertain is forced into ``outside`` — reps learn the check is noise, managers learn to
ignore it. Here:

* :func:`classify` treats the fix as a circle of radius ``accuracy``: ``inside`` only when
  the whole circle is inside, ``outside`` only when the whole circle is outside, otherwise
  ``uncertain``. A fix worse than the policy's ``max_fix_accuracy_m`` is no evidence
  (``no_fix``). No target is ``not_configured``; a remote channel is ``not_applicable``.
* :func:`target_radius` scales the fallback radius by how much we trust the place's
  coordinates (a geocoder's guess in a village is often a street off).
* :func:`decide` applies the enforcement mode — and never rejects what already happened
  offline: a visit the server would have blocked is accepted and flagged for review.

The mobile app evaluates offline with a port of these same functions; the shared case
table is ``tests/fixtures/fieldops_classify_cases.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.fieldops.enums import (
    AnomalyType,
    Channel,
    CheckAction,
    CheckResult,
    Enforcement,
    Severity,
)

#: Bump when a rule below changes; stored on every ``location_checks`` row.
EVALUATOR_VERSION = 1


def classify(
    distance_m: float | None,
    radius_m: float | None,
    accuracy_m: float | None,
    *,
    channel: str = Channel.FIELD.value,
    max_accuracy_m: float = 100.0,
) -> CheckResult:
    """Accuracy-aware verdict for one fix against one target."""
    if channel != Channel.FIELD.value:
        return CheckResult.NOT_APPLICABLE
    if radius_m is None:
        return CheckResult.NOT_CONFIGURED
    if distance_m is None or accuracy_m is None or accuracy_m > max_accuracy_m:
        return CheckResult.NO_FIX
    if distance_m + accuracy_m <= radius_m:
        return CheckResult.INSIDE
    if distance_m - accuracy_m > radius_m:
        return CheckResult.OUTSIDE
    return CheckResult.UNCERTAIN


def classify_polygon(
    covered: bool | None,
    edge_distance_m: float | None,
    accuracy_m: float | None,
    *,
    channel: str = Channel.FIELD.value,
    max_accuracy_m: float = 100.0,
) -> CheckResult:
    """The polygon form of :func:`classify`: ``covered`` = the fix's centre is inside the polygon,
    ``edge_distance_m`` = its distance to the polygon's boundary. The accuracy circle must clear the
    edge for a confident verdict either way."""
    if channel != Channel.FIELD.value:
        return CheckResult.NOT_APPLICABLE
    if covered is None or edge_distance_m is None or accuracy_m is None or accuracy_m > max_accuracy_m:
        return CheckResult.NO_FIX
    if covered and edge_distance_m >= accuracy_m:
        return CheckResult.INSIDE
    if not covered and edge_distance_m > accuracy_m:
        return CheckResult.OUTSIDE
    return CheckResult.UNCERTAIN


def target_radius(verification_status: str | None, *, base_m: float, geocoded_factor: float) -> float | None:
    """Radius for a place WITHOUT a drawn geofence, from the provenance of its coordinates.

    ``field_verified`` → the policy radius; ``geocoded_only`` → scaled up; anything else
    (unverified, disputed, unknown) → ``None`` = not configured. A disputed point must not
    judge anyone.
    """
    if verification_status == "field_verified":
        return float(base_m)
    if verification_status == "geocoded_only":
        return float(base_m) * float(geocoded_factor)
    return None


@dataclass(frozen=True, slots=True)
class Decision:
    action: CheckAction
    #: the error code to raise instead of proceeding (online only), or None
    block_code: str | None = None
    anomaly: AnomalyType | None = None
    severity: Severity | None = None
    review_pending: bool = False


def decide(result: CheckResult, enforcement: Enforcement | str, *, offline: bool, justified: bool) -> Decision:
    """What happens to a visit START given the verdict and the enforcement mode.

    ============  ======================  ==============================================
    mode          outside, online         outside, offline replay
    ============  ======================  ==============================================
    advisory      recorded + warning      recorded + warning
    soft_block    422 justification       accepted: justified (info) or bypassed (warn)
                  unless justified
    hard_block    422 outside_geofence    accepted, bypassed_offline (critical)
    ============  ======================  ==============================================

    ``uncertain`` / ``no_fix`` never block (under hard_block they are treated as soft, which
    also does not block them); ``inside``, ``not_configured`` and ``not_applicable`` are
    simply recorded.
    """
    mode = Enforcement(enforcement)
    if result is not CheckResult.OUTSIDE:
        return Decision(CheckAction.RECORDED)

    if mode is Enforcement.ADVISORY:
        return Decision(CheckAction.RECORDED, anomaly=AnomalyType.OUTSIDE_GEOFENCE, severity=Severity.WARNING)

    if mode is Enforcement.SOFT_BLOCK:
        if justified:
            return Decision(CheckAction.JUSTIFIED, anomaly=AnomalyType.JUSTIFIED_OUTSIDE, severity=Severity.INFO,
                            review_pending=True)
        if offline:
            return Decision(CheckAction.BYPASSED_OFFLINE, anomaly=AnomalyType.OUTSIDE_GEOFENCE,
                            severity=Severity.WARNING, review_pending=True)
        return Decision(CheckAction.JUSTIFICATION_REQUIRED, block_code="justification_required")

    if offline:
        return Decision(CheckAction.BYPASSED_OFFLINE, anomaly=AnomalyType.HARD_BLOCK_BYPASSED_OFFLINE,
                        severity=Severity.CRITICAL, review_pending=True)
    return Decision(CheckAction.BLOCKED, block_code="outside_geofence")


__all__ = ["EVALUATOR_VERSION", "Decision", "classify", "classify_polygon", "decide", "target_radius"]
