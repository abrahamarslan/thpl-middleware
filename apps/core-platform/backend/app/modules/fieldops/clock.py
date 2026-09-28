"""Business time for events reported by an offline-first device — PURE, no I/O.

The server's receipt time is not when something happened: a rep who starts a shift offline
at 09:02 and syncs at 18:40 did not start at 18:40. The device's wall clock is not
trustworthy either (users change it; it drifts). So every event is timed from three clocks:

    client_timestamp      the device wall clock at the event (raw, kept for diagnostics)
    elapsed_realtime_ms   the device MONOTONIC clock at the event (Android
    + boot_count          SystemClock.elapsedRealtime / iOS systemUptime) — not user-settable,
                          resets on reboot
    received_at           the server's clock at ingest

plus the device's clocks AT SEND, from the request headers (``X-Device-Sent-At``,
``X-Device-Elapsed-Ms``, ``X-Device-Boot-Count``). :func:`derive` picks the best evidence:

1. ``monotonic``: same boot → ``received_at − (sent_elapsed − event_elapsed)``;
2. ``wall_clock_corrected``: ``client_timestamp + (received_at − sent_at)`` — the skew
   measured at send removes a wrong-but-stable device clock;
3. ``device_wall_clock``: a legacy client sent no send-time headers → the raw device time;
4. ``server_receipt``: nothing usable.

The result is never in the future (capped at ``received_at``) and never implausibly old
(older than :data:`MAX_BACKDATE` falls back to receipt time). Network latency is inside
``received_at − sent_at``: far below any KPI's resolution.

The same function times pings, shift/pause/visit transitions, tasks and device events, so a
visit's ``started_at`` and its ``visit_start`` checkpoint can never disagree.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.modules.fieldops.enums import TimeBasis

#: Older than this is not an offline replay but a broken clock.
MAX_BACKDATE = dt.timedelta(days=45)
#: A partition key more than this in the future is clamped (see :func:`partition_key`).
MAX_FUTURE = dt.timedelta(minutes=10)
#: Received this long after it happened = a stale replay (diagnostic flag, not an error).
STALE_AFTER = dt.timedelta(hours=24)

DEFAULT_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True, slots=True)
class SendContext:
    """The device's clocks at SEND time (request headers) and the server's receipt time."""

    received_at: dt.datetime
    sent_at: dt.datetime | None = None
    sent_elapsed_ms: int | None = None
    boot_count: int | None = None
    session_uuid: uuid_lib.UUID | None = None


@dataclass(frozen=True, slots=True)
class EventClock:
    """The device's clocks at the EVENT."""

    client_timestamp: dt.datetime | None = None
    elapsed_realtime_ms: int | None = None
    boot_count: int | None = None


@dataclass(frozen=True, slots=True)
class Derived:
    occurred_at: dt.datetime
    time_basis: TimeBasis
    clock_skew_ms: int | None

    @property
    def basis(self) -> str:
        return self.time_basis.value


def utc(value: dt.datetime | None) -> dt.datetime | None:
    """Aware UTC; a naive datetime is taken to be UTC (the wire contract is ISO-8601 with offset)."""
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def skew_ms(send: SendContext) -> int | None:
    sent_at = utc(send.sent_at)
    if sent_at is None:
        return None
    return int((utc(send.received_at) - sent_at).total_seconds() * 1000)


def derive(send: SendContext, event: EventClock | None) -> Derived:
    """Business time of one event. See the module docstring for the rules."""
    received = utc(send.received_at)
    skew = skew_ms(send)
    event = event or EventClock()
    wall = utc(event.client_timestamp)

    occurred: dt.datetime | None = None
    basis = TimeBasis.SERVER_RECEIPT
    if (
        event.elapsed_realtime_ms is not None and send.sent_elapsed_ms is not None
        and event.boot_count is not None and send.boot_count is not None
        and event.boot_count == send.boot_count
        and 0 <= event.elapsed_realtime_ms <= send.sent_elapsed_ms
    ):
        occurred = received - dt.timedelta(milliseconds=send.sent_elapsed_ms - event.elapsed_realtime_ms)
        basis = TimeBasis.MONOTONIC
    elif wall is not None and skew is not None:
        occurred = wall + dt.timedelta(milliseconds=skew)
        basis = TimeBasis.WALL_CLOCK_CORRECTED
    elif wall is not None:
        occurred = wall
        basis = TimeBasis.DEVICE_WALL_CLOCK

    if occurred is None or occurred < received - MAX_BACKDATE:
        return Derived(received, TimeBasis.SERVER_RECEIPT, skew)
    occurred = min(occurred, received)
    return Derived(occurred, basis, skew)


def partition_key(client_timestamp: dt.datetime | None, received_at: dt.datetime) -> tuple[dt.datetime, bool]:
    """``location_pings.recorded_at`` and whether it was clamped.

    The DEVICE time as reported — stable across replays, which is what lets the unique index
    dedupe them — unless it is absurd. A far-future key would sit in the DEFAULT partition and
    make pg_partman's later creation of that month's partition fail; a far-past one would land
    in a partition retention already dropped. Clamped rows are flagged and deduped by Redis
    instead (their key is no longer stable).
    """
    received = utc(received_at)
    stamp = utc(client_timestamp)
    if stamp is None:
        return received, True
    if stamp > received + MAX_FUTURE or stamp < received - MAX_BACKDATE:
        return received, True
    return stamp, False


def business_date(occurred_at: dt.datetime, timezone: str | None) -> dt.date:
    """The business day of an instant in the ORGANIZATION's timezone — never the device's."""
    try:
        zone = ZoneInfo(timezone or DEFAULT_TIMEZONE)
    except (KeyError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return utc(occurred_at).astimezone(zone).date()


def local_time(occurred_at: dt.datetime, timezone: str | None) -> dt.time:
    try:
        zone = ZoneInfo(timezone or DEFAULT_TIMEZONE)
    except (KeyError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return utc(occurred_at).astimezone(zone).time()


__all__ = [
    "DEFAULT_TIMEZONE", "MAX_BACKDATE", "MAX_FUTURE", "STALE_AFTER",
    "Derived", "EventClock", "SendContext",
    "business_date", "derive", "local_time", "partition_key", "skew_ms", "utc",
]
