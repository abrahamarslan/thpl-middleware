"""Quota-day and pacing-curve maths (pure, no infrastructure)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.zoho.core.pacing import PacingCurve, allowance, quota_day


def ist(y, m, d, hh=0, mm=0):
    """A UTC instant expressed from IST wall-clock (IST = UTC+5:30)."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5, minutes=30)


def test_quota_day_key_follows_the_configured_timezone():
    # 00:30 IST on the 18th is still 19:00 UTC on the 17th
    day = quota_day(datetime(2026, 9, 17, 19, 0, tzinfo=UTC), timezone="Asia/Kolkata")
    assert day.key == "20260918"
    assert day.start.hour == 0 and day.end - day.start == timedelta(days=1)


def test_quota_day_respects_a_non_midnight_boundary():
    before = quota_day(ist(2026, 9, 18, 5, 0), timezone="Asia/Kolkata", day_start="06:00")
    after = quota_day(ist(2026, 9, 18, 7, 0), timezone="Asia/Kolkata", day_start="06:00")
    assert before.key == "20260917"
    assert after.key == "20260918"
    assert after.start.hour == 6


def test_quota_day_falls_back_to_utc_for_an_unknown_timezone():
    day = quota_day(datetime(2026, 9, 18, 12, 0, tzinfo=UTC), timezone="Mars/Olympus")
    assert day.timezone == "UTC"


def test_elapsed_fraction_is_clamped():
    day = quota_day(ist(2026, 9, 18, 12, 0))
    assert day.elapsed_fraction(day.start - timedelta(hours=1)) == 0.0
    assert day.elapsed_fraction(day.end + timedelta(hours=1)) == 1.0
    assert 0.49 < day.elapsed_fraction(day.start + timedelta(hours=12)) < 0.51


def test_curve_none_unlocks_everything_immediately():
    day = quota_day(ist(2026, 9, 18, 0, 1))
    assert allowance(day.start, day, ceiling=44_000, curve=PacingCurve.NONE) == 44_000


def test_linear_curve_grows_with_the_day():
    day = quota_day(ist(2026, 9, 18, 0, 0))
    at_start = allowance(day.start, day, ceiling=10_000, curve=PacingCurve.LINEAR, carry_pct=0.0)
    at_noon = allowance(day.start + timedelta(hours=12), day, ceiling=10_000,
                        curve=PacingCurve.LINEAR, carry_pct=0.0)
    at_end = allowance(day.end, day, ceiling=10_000, curve=PacingCurve.LINEAR, carry_pct=0.0)
    assert at_start == 0
    assert 4_900 <= at_noon <= 5_100
    assert at_end == 10_000


def test_business_curve_front_loads_business_hours():
    day = quota_day(ist(2026, 9, 18, 0, 0))
    kwargs = dict(ceiling=10_000, curve=PacingCurve.BUSINESS,
                  business_hours="07:00-21:00", business_share=0.7, carry_pct=0.0)

    pre_business = allowance(day.start + timedelta(hours=7), day, **kwargs)     # 07:00
    midday = allowance(day.start + timedelta(hours=14), day, **kwargs)          # 14:00
    end_of_business = allowance(day.start + timedelta(hours=21), day, **kwargs)  # 21:00
    end_of_day = allowance(day.end, day, **kwargs)

    # night before business gets the night share only (7h of the 10h night)
    assert 1_900 <= pre_business <= 2_200
    assert midday > pre_business
    assert 8_900 <= end_of_business <= 9_200
    assert end_of_day == 10_000


def test_carry_lets_short_bursts_through_without_exceeding_the_ceiling():
    day = quota_day(ist(2026, 9, 18, 0, 0))
    at_start = allowance(day.start, day, ceiling=10_000, curve=PacingCurve.LINEAR, carry_pct=0.05)
    at_end = allowance(day.end, day, ceiling=10_000, curve=PacingCurve.LINEAR, carry_pct=0.05)
    assert at_start == 500
    assert at_end == 10_000


@pytest.mark.parametrize("hours", ["07:00-21:00", "21:00-07:00", "garbage"])
def test_business_hours_parsing_never_raises(hours):
    day = quota_day(ist(2026, 9, 18, 10, 0))
    value = allowance(day.start + timedelta(hours=10), day, ceiling=1_000,
                      curve=PacingCurve.BUSINESS, business_hours=hours)
    assert 0 <= value <= 1_000
