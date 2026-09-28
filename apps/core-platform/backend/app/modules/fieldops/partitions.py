"""Monthly partitions of ``fieldops.location_pings`` — created ahead, dropped at the retention horizon.

Same doctrine as ``zoho/control/retention.py``: pg_partman is deliberately not used (the scratch
test image does not ship it — a migration that cannot run in CI is not a migration), so the
application keeps partitions ``location_pings_pYYYYMM`` for the current month and
:data:`MONTHS_AHEAD` ahead, bounded at UTC month starts (the bounds the migration used).

Postgres refuses to create a partition whose range already has rows in the DEFAULT partition.
Ingest clamps the partition key to at most ten minutes in the future, so that only happens if
maintenance fell a month behind; such a period is logged and stays in DEFAULT (correct, just not
pruned by partition drop — the retention sweep deletes DEFAULT rows by ``occurred_at``).

Retention: ``compliance.data_retention_schedules('location_history')`` decides how long fixes are
kept. Nothing is dropped unless that rule has ``auto_purge_enabled`` — deleting location history
is a DPDP decision, not a default.
"""

from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("app.fieldops.partitions")

PARENT = "fieldops.location_pings"
BARE = "location_pings"
SCHEMA = "fieldops"
MONTHS_AHEAD = 3
RETENTION_CATEGORY = "location_history"


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def add_months(day: dt.date, months: int) -> dt.date:
    index = day.year * 12 + (day.month - 1) + months
    return dt.date(index // 12, index % 12 + 1, 1)


def partition_name(month: dt.date) -> str:
    return f"{BARE}_p{month:%Y%m}"


def bounds(month: dt.date) -> tuple[dt.datetime, dt.datetime]:
    start = dt.datetime.combine(month_start(month), dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(add_months(month_start(month), 1), dt.time.min, tzinfo=dt.UTC)
    return start, end


async def ensure_partitions(db: AsyncSession, *, today: dt.date | None = None, ahead: int = MONTHS_AHEAD) -> list[str]:
    """Create the current month's and ``ahead`` future months' partitions. Idempotent."""
    today = today or dt.datetime.now(dt.UTC).date()
    created = []
    for offset in range(ahead + 1):
        month = add_months(month_start(today), offset)
        name = partition_name(month)
        if await db.scalar(text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"{SCHEMA}.{name}"}):
            continue
        start, end = bounds(month)
        try:
            async with db.begin_nested():
                await db.execute(text(
                    f"CREATE TABLE {SCHEMA}.{name} PARTITION OF {PARENT} "
                    f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
                ))
            created.append(name)
        except Exception as exc:  # noqa: BLE001 — rows for that month already sit in DEFAULT
            logger.warning("fieldops.partitions.create_failed", partition=name, error=str(exc)[:300])
    if created:
        logger.info("fieldops.partitions.created", partitions=created)
    return created


async def list_partitions(db: AsyncSession) -> list[tuple[str, dt.date]]:
    rows = (await db.execute(text("""
        SELECT c.relname FROM pg_inherits i
          JOIN pg_class c ON c.oid = i.inhrelid
          JOIN pg_class p ON p.oid = i.inhparent
          JOIN pg_namespace n ON n.oid = p.relnamespace
         WHERE p.relname = :parent AND n.nspname = :schema
    """), {"parent": BARE, "schema": SCHEMA})).scalars().all()
    out = []
    for name in rows:
        suffix = name.rsplit("_p", 1)[-1]
        if len(suffix) == 6 and suffix.isdigit():
            out.append((name, dt.date(int(suffix[:4]), int(suffix[4:]), 1)))
    return sorted(out, key=lambda item: item[1])


async def retention_days(db: AsyncSession) -> int | None:
    """Days to keep fixes, or None when the rule is absent, inactive or auto-purge is off."""
    row = (await db.execute(text(
        "SELECT retention_period_days + grace_period_days AS days, auto_purge_enabled, legal_hold_exception "
        "FROM data_retention_schedules WHERE data_category = :c AND deactivation_date IS NULL"
    ), {"c": RETENTION_CATEGORY})).first()
    if row is None or not row.auto_purge_enabled:
        return None
    return int(row.days)


async def apply_retention(db: AsyncSession, *, today: dt.date | None = None, batch: int = 10_000) -> dict:
    """Drop monthly partitions wholly older than the retention window; purge DEFAULT-partition rows
    older than it in batches. A no-op while auto-purge is off."""
    days = await retention_days(db)
    if days is None:
        return {"dropped": [], "purged_default": 0, "skipped": "auto_purge_disabled"}
    today = today or dt.datetime.now(dt.UTC).date()
    horizon = dt.datetime.combine(today - dt.timedelta(days=days), dt.time.min, tzinfo=dt.UTC)
    dropped = []
    for name, month in await list_partitions(db):
        _, end = bounds(month)
        if end <= horizon:
            await db.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.{name}"))
            dropped.append(name)
    purged = 0
    while True:
        result = await db.execute(text(f"""
            DELETE FROM {SCHEMA}.{BARE}_default
             WHERE ctid IN (SELECT ctid FROM {SCHEMA}.{BARE}_default WHERE occurred_at < :h LIMIT :n)
        """), {"h": horizon, "n": batch})
        purged += result.rowcount or 0
        if not result.rowcount or result.rowcount < batch:
            break
    if dropped or purged:
        logger.info("fieldops.retention.applied", dropped=dropped, purged_default=purged, keep_days=days)
    return {"dropped": dropped, "purged_default": purged}


__all__ = ["add_months", "apply_retention", "bounds", "ensure_partitions", "list_partitions", "partition_name",
           "retention_days"]
