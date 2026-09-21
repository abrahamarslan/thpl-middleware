"""Quota-day arithmetic and the background pacing curve (pure, testable).

Two jobs, both deliberately free of I/O so they can be property-tested:

  1. ``quota_day()`` — which Zoho "day" we are in. Zoho's daily call limit
     resets on its own schedule; we model it as a configurable timezone plus a
     day-start time so the boundary can be corrected once Phase 0 observes the
     real reset (delta §3.2 [verify]).
  2. ``allowance()`` — how many background calls the engine may have spent by
     now. A hard daily ceiling alone lets a morning backfill starve the
     evening; the curve spreads background work across the day while leaving
     interactive, push and webhook-refresh traffic unpaced.

Only *background* priorities (incremental scans, reconcile, reports, bulk
sync requests) are subject to the curve. Pushes and refreshes obey the
governor's state machine only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger("app.zoho.pacing")


class PacingCurve(StrEnum):
    NONE = "none"          # background may spend the whole allowance at once
    LINEAR = "linear"      # allowance grows with the fraction of the day elapsed
    BUSINESS = "business"  # most of the allowance during business hours


@dataclass(frozen=True, slots=True)
class QuotaDay:
    """One Zoho quota day: its key, its bounds and how long to keep counters."""

    key: str                 # e.g. "20260918" — Redis/Postgres day key
    start: datetime          # tz-aware, inclusive
    end: datetime            # tz-aware, exclusive
    timezone: str

    @property
    def ttl_seconds(self) -> int:
        """Keep counters a little past the boundary for post-mortems."""
        return int((self.end - self.start).total_seconds()) + 7200

    def elapsed_fraction(self, now: datetime) -> float:
        total = (self.end - self.start).total_seconds()
        if total <= 0:
            return 1.0
        return min(max((now - self.start).total_seconds() / total, 0.0), 1.0)

    def resets_at_iso(self) -> str:
        return self.end.isoformat()


def load_timezone(name: str) -> ZoneInfo:
    """Resolve a timezone name, falling back to UTC with a loud log.

    Slim container images sometimes ship without the tz database; the engine
    must keep running (UTC boundary) rather than refuse to start.
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.error("zoho_timezone_unavailable", requested=name, fallback="UTC")
        return ZoneInfo("UTC")


def parse_hhmm(value: str, *, default: time) -> time:
    try:
        hour, _, minute = value.strip().partition(":")
        return time(hour=int(hour), minute=int(minute or 0))
    except (ValueError, TypeError):
        logger.warning("zoho_invalid_time_setting", value=value, fallback=default.isoformat())
        return default


def quota_day(now: datetime, *, timezone: str = "Asia/Kolkata", day_start: str = "00:00") -> QuotaDay:
    """The quota day containing ``now``."""
    tz = load_timezone(timezone)
    start_time = parse_hhmm(day_start, default=time(0, 0))
    local = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(tz)

    day: date = local.date()
    start = datetime.combine(day, start_time, tzinfo=tz)
    if local < start:                      # before today's boundary → previous day
        day = day - timedelta(days=1)
        start = datetime.combine(day, start_time, tzinfo=tz)
    end = start + timedelta(days=1)
    return QuotaDay(key=day.strftime("%Y%m%d"), start=start, end=end, timezone=str(tz))


def _business_fraction(
    now: datetime,
    day: QuotaDay,
    *,
    business_start: time,
    business_end: time,
    business_share: float,
) -> float:
    """Cumulative fraction of the daily allowance unlocked by ``now``."""
    tz = day.start.tzinfo
    local_now = now.astimezone(tz)
    b_start = datetime.combine(day.start.date(), business_start, tzinfo=tz)
    b_end = datetime.combine(day.start.date(), business_end, tzinfo=tz)
    if b_end <= b_start:                    # window crosses midnight → clamp to day end
        b_end = day.end

    b_start = max(b_start, day.start)
    b_end = min(b_end, day.end)

    business_total = (b_end - b_start).total_seconds()
    day_total = (day.end - day.start).total_seconds()
    night_total = max(day_total - business_total, 0.0)

    if business_total <= 0:
        return day.elapsed_fraction(now)

    business_elapsed = min(max((local_now - b_start).total_seconds(), 0.0), business_total)
    night_elapsed = max((local_now - day.start).total_seconds(), 0.0) - business_elapsed
    night_elapsed = min(max(night_elapsed, 0.0), night_total)

    night_share = 1.0 - business_share
    night_part = (night_elapsed / night_total) * night_share if night_total > 0 else 0.0
    business_part = (business_elapsed / business_total) * business_share
    return min(night_part + business_part, 1.0)


def allowance(
    now: datetime,
    day: QuotaDay,
    *,
    ceiling: int,
    curve: PacingCurve | str = PacingCurve.BUSINESS,
    business_hours: str = "07:00-21:00",
    business_share: float = 0.7,
    carry_pct: float = 0.05,
) -> int:
    """How many background calls may have been spent by ``now`` (absolute count).

    ``carry_pct`` lets short bursts through without breaking the shape of the
    curve; the ceiling is never exceeded.
    """
    curve = PacingCurve(str(curve))
    if curve is PacingCurve.NONE:
        return ceiling

    if curve is PacingCurve.LINEAR:
        fraction = day.elapsed_fraction(now)
    else:
        start_raw, _, end_raw = business_hours.partition("-")
        fraction = _business_fraction(
            now,
            day,
            business_start=parse_hhmm(start_raw, default=time(7, 0)),
            business_end=parse_hhmm(end_raw, default=time(21, 0)),
            business_share=min(max(business_share, 0.0), 1.0),
        )

    return int(min(fraction + max(carry_pct, 0.0), 1.0) * ceiling)


__all__ = ["PacingCurve", "QuotaDay", "allowance", "load_timezone", "parse_hhmm", "quota_day"]
