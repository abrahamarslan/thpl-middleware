"""Type-safe, DST-aware time and timezone utility built on `whenever`.

Doctrine:
- In-memory domain operations: Use `whenever.Instant` and `whenever.ZonedDateTime`.
- Persistence boundary (SQLAlchemy / asyncpg): Convert to/from UTC aware stdlib datetime.
- API & formatting boundary: ISO-8601 strings or formatted local strings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator
import whenever
from whenever import Instant, PlainDateTime, ZonedDateTime


def now_utc() -> Instant:
    """Return current moment as an Instant (exact point in time, UTC)."""
    return Instant.now()


def now_in_tz(iana_tz: str = "Asia/Kolkata") -> ZonedDateTime:
    """Return current moment zoned in the given IANA timezone."""
    return Instant.now().to_tz(iana_tz)


def to_user_tz(moment: Instant | ZonedDateTime | datetime, iana_tz: str = "Asia/Kolkata") -> ZonedDateTime:
    """Convert an Instant, ZonedDateTime, or aware/naive datetime to user's local timezone."""
    if isinstance(moment, ZonedDateTime):
        return moment.to_tz(iana_tz)
    if isinstance(moment, datetime):
        if moment.tzinfo is None:
            # Assume UTC for naive timestamps from database
            instant = Instant.from_utc(
                moment.year,
                moment.month,
                moment.day,
                moment.hour,
                moment.minute,
                moment.second,
                nanosecond=moment.microsecond * 1000,
            )
        else:
            instant = Instant(moment)
    else:
        instant = moment
    return instant.to_tz(iana_tz)


def format_user_datetime(
    moment: Instant | ZonedDateTime | datetime | None = None,
    iana_tz: str = "Asia/Kolkata",
    fmt: str | None = None,
) -> str:
    """Format a timestamp in the user's timezone for displays and emails.

    Default format: 'YYYY-MM-DD HH:mm:ss'
    """
    if moment is None:
        target = now_utc()
    elif isinstance(moment, datetime):
        target = Instant(moment if moment.tzinfo else moment.replace(tzinfo=UTC))
    elif isinstance(moment, ZonedDateTime):
        target = moment.to_instant()
    else:
        target = moment

    zoned = target.to_tz(iana_tz)
    if fmt:
        return zoned.format(fmt)
    # Default clean format
    return f"{zoned.year:04d}-{zoned.month:02d}-{zoned.day:02d} {zoned.hour:02d}:{zoned.minute:02d}:{zoned.second:02d}"


def format_user_datetime_display(
    moment: Instant | ZonedDateTime | datetime | None = None,
    iana_tz: str = "Asia/Kolkata",
) -> str:
    """Format a timestamp in the user's timezone for human-facing emails and UI displays.

    Example: 'September 17, 2026, 17:20 IST'
    """
    if moment is None:
        target = now_utc()
    elif isinstance(moment, datetime):
        target = Instant(moment if moment.tzinfo else moment.replace(tzinfo=UTC))
    elif isinstance(moment, ZonedDateTime):
        target = moment.to_instant()
    else:
        target = moment

    try:
        zoned = target.to_tz(iana_tz)
    except Exception:
        zoned = target.to_tz("UTC")

    py_dt = zoned.to_stdlib()
    tz_label = py_dt.tzname() or iana_tz
    return f"{py_dt:%B} {py_dt.day}, {py_dt:%Y, %H:%M} {tz_label}"


def to_db_utc(moment: Instant | ZonedDateTime | datetime) -> datetime:
    """Convert a whenever object to a standard library timezone-aware UTC datetime for asyncpg/SQLAlchemy."""
    if isinstance(moment, datetime):
        return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    if isinstance(moment, ZonedDateTime):
        return moment.to_instant().to_stdlib()
    return moment.to_stdlib()


def from_db_utc(dt: datetime) -> Instant:
    """Convert a standard library datetime from database into an Instant."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return Instant(dt)


def parse_iso(iso_str: str) -> Instant:
    """Safely parse an ISO-8601 string into an Instant."""
    return Instant.parse_iso(iso_str)


def is_valid_iana_timezone(iana_name: str) -> bool:
    """Check if a string is a valid IANA timezone identifier."""
    if not iana_name or not isinstance(iana_name, str):
        return False
    try:
        Instant.now().to_tz(iana_name.strip())
        return True
    except Exception:
        return False


class WheneverInstant(TypeDecorator):
    """SQLAlchemy TypeDecorator that seamlessly maps UTC TIMESTAMP WITH TIME ZONE
    columns to/from `whenever.Instant` instances.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (Instant, ZonedDateTime)):
            return to_db_utc(value)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, datetime):
            return from_db_utc(value)
        return value
