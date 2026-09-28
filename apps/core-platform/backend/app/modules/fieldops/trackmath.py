"""Track arithmetic — PURE, no I/O: fix quality, movement, coverage, gaps, dwell, intervals.

Used by ingest (per-fix quality flags), metrics (time buckets, distance, coverage) and
dwell detection (geofence entry/exit). Distances are straight-line haversine from
``geo/distance.py`` — right for "how far did the rep move" at jitter-filtered resolution;
anything billed by distance belongs to PostGIS / a routing provider.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from app.modules.fieldops.enums import MOVING_ACTIVITIES, UNTRUSTED_FLAGS, QualityFlag
from app.modules.geo.distance import distance_m

#: Faster than this between two fixes is not a two-wheeler on a Gujarat road — it is a bad fix.
IMPOSSIBLE_SPEED_MPS = 250 / 3.6
#: Above this displacement speed a fix pair counts as moving.
MOVING_SPEED_MPS = 0.8
#: Activity-recognition confidence needed to trust "moving" from the OS.
ACTIVITY_CONFIDENCE_MIN = 60


@dataclass(frozen=True, slots=True)
class Fix:
    occurred_at: dt.datetime
    latitude: float | None
    longitude: float | None
    accuracy_m: float | None = None
    speed_mps: float | None = None
    flags: int = 0
    activity_type: str | None = None
    activity_confidence: int | None = None
    is_mock: bool = False

    @property
    def has_position(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def point(self) -> tuple[float, float]:
        return (float(self.latitude), float(self.longitude))  # type: ignore[arg-type]


Interval = tuple[dt.datetime, dt.datetime]


# ── fix quality ─────────────────────────────────────────────────────────────

def implied_speed_mps(a: Fix, b: Fix) -> float | None:
    """Displacement speed between two fixes (None when either has no position or Δt = 0)."""
    if not (a.has_position and b.has_position):
        return None
    seconds = abs((b.occurred_at - a.occurred_at).total_seconds())
    if seconds <= 0:
        return None
    return distance_m(a.point, b.point) / seconds


def is_impossible_hop(previous: Fix | None, current: Fix) -> bool:
    """Would reaching ``current`` from ``previous`` need more than :data:`IMPOSSIBLE_SPEED_MPS`?

    The two accuracy radii are forgiven first: two ±50 m fixes a second apart are not a
    100 m/s journey.
    """
    if previous is None or not (previous.has_position and current.has_position):
        return False
    seconds = abs((current.occurred_at - previous.occurred_at).total_seconds())
    if seconds <= 0:
        return False
    slack = (previous.accuracy_m or 0) + (current.accuracy_m or 0)
    meters = max(0.0, distance_m(previous.point, current.point) - slack)
    return meters / seconds > IMPOSSIBLE_SPEED_MPS


def same_coordinates(a: Fix | None, b: Fix) -> bool:
    """Identical to 6 decimals (~0.1 m) — real GNSS jitters; a replayed/spoofed feed does not."""
    if a is None or not (a.has_position and b.has_position):
        return False
    return round(float(a.latitude), 6) == round(float(b.latitude), 6) and \
        round(float(a.longitude), 6) == round(float(b.longitude), 6)


def trusted(fix: Fix, *, max_accuracy_m: float) -> bool:
    """Usable as evidence / movement: positioned, accurate enough, not mock or implausible."""
    if not fix.has_position or fix.is_mock or fix.flags & int(UNTRUSTED_FLAGS):
        return False
    return fix.accuracy_m is None or fix.accuracy_m <= max_accuracy_m


def accepted(fixes: Iterable[Fix], *, max_accuracy_m: float) -> list[Fix]:
    return sorted((f for f in fixes if trusted(f, max_accuracy_m=max_accuracy_m)), key=lambda f: f.occurred_at)


# ── intervals ───────────────────────────────────────────────────────────────

def merge(intervals: Iterable[Interval]) -> list[Interval]:
    ordered = sorted((s, e) for s, e in intervals if e > s)
    out: list[Interval] = []
    for start, end in ordered:
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def clip(intervals: Iterable[Interval], window: Interval) -> list[Interval]:
    lo, hi = window
    return [(max(s, lo), min(e, hi)) for s, e in intervals if min(e, hi) > max(s, lo)]


def subtract(base: Iterable[Interval], holes: Iterable[Interval]) -> list[Interval]:
    """``base`` minus every hole (both merged first)."""
    result = merge(base)
    for h_start, h_end in merge(holes):
        next_result: list[Interval] = []
        for start, end in result:
            if h_end <= start or h_start >= end:
                next_result.append((start, end))
                continue
            if h_start > start:
                next_result.append((start, h_start))
            if h_end < end:
                next_result.append((h_end, end))
        result = next_result
    return result


def minutes(intervals: Iterable[Interval]) -> float:
    return sum((e - s).total_seconds() for s, e in merge(intervals)) / 60


def overlap_minutes(a: Iterable[Interval], b: Iterable[Interval]) -> float:
    total = 0.0
    b_merged = merge(b)
    for s, e in merge(a):
        total += minutes(clip(b_merged, (s, e)))
    return total


# ── movement ────────────────────────────────────────────────────────────────

def is_moving(a: Fix, b: Fix) -> bool:
    """Is the pair (a → b) movement? The OS activity (when confident) wins; else displacement speed
    beyond the accuracy radius."""
    if b.activity_type and (b.activity_confidence or 0) >= ACTIVITY_CONFIDENCE_MIN:
        return b.activity_type in MOVING_ACTIVITIES
    seconds = (b.occurred_at - a.occurred_at).total_seconds()
    if seconds <= 0 or not (a.has_position and b.has_position):
        return False
    meters = distance_m(a.point, b.point)
    if meters <= max(a.accuracy_m or 0, b.accuracy_m or 0):
        return False                                    # inside the noise
    return meters / seconds >= MOVING_SPEED_MPS


def moving_intervals(fixes: Sequence[Fix], *, max_gap: dt.timedelta) -> list[Interval]:
    """Intervals between consecutive trusted fixes that are movement. A pair further apart than
    ``max_gap`` is a GAP, not evidence of anything."""
    out: list[Interval] = []
    for a, b in pairwise(fixes):
        if b.occurred_at - a.occurred_at > max_gap:
            continue
        if is_moving(a, b):
            out.append((a.occurred_at, b.occurred_at))
    return merge(out)


def distance_km(fixes: Sequence[Fix]) -> float:
    """Σ straight-line hops between consecutive trusted fixes, ignoring hops inside the accuracy
    radius (standing still with ±30 m jitter is not 30 m of travel per fix)."""
    total = 0.0
    anchor: Fix | None = None
    for fix in fixes:
        if not fix.has_position:
            continue
        if anchor is None:
            anchor = fix
            continue
        meters = distance_m(anchor.point, fix.point)
        if meters > max(anchor.accuracy_m or 0, fix.accuracy_m or 0, 5.0):
            total += meters
            anchor = fix
    return total / 1000


# ── coverage ────────────────────────────────────────────────────────────────

def coverage(
    fix_times: Sequence[dt.datetime], windows: Sequence[Interval], *, bucket: dt.timedelta,
) -> tuple[float | None, float]:
    """(coverage %, longest gap in minutes) of fixes over the tracked windows.

    A window is cut into buckets of ``bucket`` (twice the expected ping interval); coverage is the
    share of buckets holding at least one fix. The longest gap counts window edges too — a shift
    whose app died at 11:00 has a gap to its end, not just between fixes.
    """
    merged = merge(windows)
    if not merged or bucket.total_seconds() <= 0:
        return None, 0.0
    times = sorted(fix_times)
    buckets = hit = 0
    longest = 0.0
    for start, end in merged:
        cursor = start
        inside = [t for t in times if start <= t <= end]
        previous = start
        for t in inside:
            longest = max(longest, (t - previous).total_seconds() / 60)
            previous = t
        longest = max(longest, (end - previous).total_seconds() / 60)
        idx = 0
        while cursor < end:
            upper = min(cursor + bucket, end)
            buckets += 1
            while idx < len(inside) and inside[idx] < cursor:
                idx += 1
            if idx < len(inside) and inside[idx] <= upper:
                hit += 1
            cursor = upper
    return (round(100.0 * hit / buckets, 2) if buckets else None), round(longest, 2)


# ── dwell ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Dwell:
    entry_at: dt.datetime | None
    exit_at: dt.datetime | None
    confidence: str             # high | medium | low


def dwell(samples: Sequence[tuple[dt.datetime, bool, float | None]], *, dwell_s: int) -> Dwell:
    """Entry = first fix of the first run of INSIDE samples spanning ≥ ``dwell_s``; exit = first fix
    of the first run of OUTSIDE samples after entry spanning ≥ ``dwell_s``. A single fix bouncing
    across the boundary never fires either (that is what the dwell threshold is for).

    ``samples`` are (occurred_at, inside?, accuracy_m), time-ordered.
    """
    def first_run(start_index: int, want_inside: bool) -> int | None:
        run_start: int | None = None
        for i in range(start_index, len(samples)):
            at, inside, _ = samples[i]
            if inside == want_inside:
                if run_start is None:
                    run_start = i
                if (at - samples[run_start][0]).total_seconds() >= dwell_s:
                    return run_start
            else:
                run_start = None
        # A run reaching the end of the data counts if it alone spans the dwell.
        return None

    entry_index = first_run(0, True)
    if entry_index is None:
        return Dwell(None, None, "low")
    exit_index = first_run(entry_index, False)
    used = samples[entry_index: exit_index if exit_index is not None else len(samples)]
    accuracies = sorted(a for _, inside, a in used if inside and a is not None)
    median = accuracies[len(accuracies) // 2] if accuracies else None
    inside_count = sum(1 for _, inside, _ in used if inside)
    if inside_count >= 3 and median is not None and median <= 30:
        confidence = "high"
    elif inside_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"
    return Dwell(samples[entry_index][0], samples[exit_index][0] if exit_index is not None else None, confidence)


def flag_bits(*flags: QualityFlag | None) -> int:
    value = 0
    for flag in flags:
        if flag:
            value |= int(flag)
    return value


__all__ = [
    "IMPOSSIBLE_SPEED_MPS", "Dwell", "Fix", "Interval",
    "accepted", "clip", "coverage", "distance_km", "dwell", "flag_bits", "implied_speed_mps",
    "is_impossible_hop", "is_moving", "merge", "minutes", "moving_intervals", "overlap_minutes",
    "same_coordinates", "subtract", "trusted",
]
