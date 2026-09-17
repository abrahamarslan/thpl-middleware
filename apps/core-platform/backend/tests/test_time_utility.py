"""Unit tests for the `whenever`-based time and timezone utility (app/common/time.py)."""

from datetime import UTC, datetime
import whenever
from whenever import Instant, PlainDateTime, ZonedDateTime, hours

from app.common.time import (
    WheneverInstant,
    format_user_datetime,
    from_db_utc,
    is_valid_iana_timezone,
    now_in_tz,
    now_utc,
    parse_iso,
    to_db_utc,
    to_user_tz,
)


def test_now_utc():
    inst = now_utc()
    assert isinstance(inst, Instant)
    # Check timestamp is reasonable (after 2026-01-01)
    assert inst.timestamp() > 1700000000


def test_now_in_tz():
    zoned = now_in_tz("Asia/Kolkata")
    assert isinstance(zoned, ZonedDateTime)
    assert zoned.tz == "Asia/Kolkata"
    assert zoned.offset.total("seconds") == 19800  # +05:30 is 19800s


def test_to_user_tz_from_instant():
    inst = Instant.from_utc(2026, 6, 15, 12, 0, 0)
    zoned = to_user_tz(inst, "Asia/Kolkata")
    assert zoned.hour == 17
    assert zoned.minute == 30
    assert zoned.day == 15


def test_to_user_tz_from_datetime():
    dt = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    zoned = to_user_tz(dt, "Asia/Kolkata")
    assert zoned.hour == 17
    assert zoned.minute == 30


def test_format_user_datetime():
    inst = Instant.from_utc(2026, 9, 17, 10, 30, 45)
    formatted = format_user_datetime(inst, "Asia/Kolkata")
    assert formatted == "2026-09-17 16:00:45"

    custom_fmt = format_user_datetime(inst, "Asia/Kolkata", fmt="YYYY/MM/DD")
    assert custom_fmt == "2026/09/17"


def test_dst_safe_arithmetic():
    # Europe/Paris springs forward on 2026-03-29: 02:00 -> 03:00 (skips 1 hour)
    start_zoned = Instant.from_utc(2026, 3, 28, 22, 0, 0).to_tz("Europe/Paris")
    assert start_zoned.hour == 23  # UTC+1

    # Adding 8 hours across the DST transition boundary
    eight_hours_later = start_zoned.add(hours=8)
    assert eight_hours_later.hour == 8  # 23 + 8 - 1 (DST leap) = 08:00 (UTC+2)


def test_is_valid_iana_timezone():
    assert is_valid_iana_timezone("Asia/Kolkata") is True
    assert is_valid_iana_timezone("America/New_York") is True
    assert is_valid_iana_timezone("Europe/London") is True
    assert is_valid_iana_timezone("Invalid/Nowhere") is False
    assert is_valid_iana_timezone("") is False


def test_db_conversions():
    inst = Instant.from_utc(2026, 5, 20, 14, 15, 30)
    db_dt = to_db_utc(inst)
    assert isinstance(db_dt, datetime)
    assert db_dt.tzinfo is not None

    roundtrip = from_db_utc(db_dt)
    assert roundtrip.exact_eq(inst)


def test_parse_iso():
    inst = parse_iso("2026-09-17T12:00:00Z")
    assert inst.timestamp() > 0
    assert inst.to_tz("UTC").hour == 12


def test_format_user_datetime_display():
    from app.common.time import format_user_datetime_display

    inst = Instant.from_utc(2026, 9, 17, 12, 0, 0)
    # Kolkata is UTC+5:30 -> 17:30 IST
    kolkata_display = format_user_datetime_display(inst, "Asia/Kolkata")
    assert "September 17, 2026, 17:30" in kolkata_display
    assert "IST" in kolkata_display

    # New York is UTC-4 in September (EDT) -> 08:00 EDT
    ny_display = format_user_datetime_display(inst, "America/New_York")
    assert "September 17, 2026, 08:00" in ny_display
    assert "EDT" in ny_display
