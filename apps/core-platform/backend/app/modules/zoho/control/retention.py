"""Retention — keep control-plane history exactly as long as policy says.

Two mechanisms, one policy table (``zoho_retention_policies``):

1. **Partition maintenance** for every RANGE-partitioned history table: create
   partitions ahead of today; drop whole partitions that are older than the
   longest policy, or older than the shortest policy and empty after the purge —
   a drop is O(1) and returns disk immediately.
2. **Batched deletes** for finer policies (a shorter keep for ``success``
   events, a longer one for ``approval``): the effective keep for each row is
   the most specific matching policy (module + class › module › class › *),
   applied 10,000 rows at a time under a time budget — never one table-wide
   DELETE that bloats WAL and locks the table.

Also purges finished ``zoho_sync_runs`` and old ``zoho_quota_days``.

**Two tables, one engine.** ``PartitionedTable`` describes what differs between
them — schema, timestamp column, primary key, period, and which column names the
retention class — so ``zoho_sync_events`` (daily, public, ``occurred_at``,
``event_type``) and ``sync.sync_payloads`` (monthly, ``sync``, ``synced_at``,
``outcome``) run the same code. Every public function still defaults to
``EVENTS``, so existing callers and tests are unchanged.

pg_partman is deliberately not used, for the reason the control-plane migration
records: the scratch test image does not ship it, and a migration that cannot
run in CI is not a migration.

Postgres refuses to create a partition whose range already has rows in the
DEFAULT partition; that only happens if partitions were not created ahead. Such
periods are logged and left in DEFAULT — the batched delete still purges them,
so correctness does not depend on the partition existing.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.modules.sync.models import PAYLOAD_CLASS
from app.modules.zoho.control.models import EVENT_CLASS, RunStatus, ZohoRetentionPolicy

logger = structlog.get_logger("app.zoho.retention")

EVENTS_TABLE = "zoho_sync_events"
PAYLOADS_TABLE = "sync.sync_payloads"
BATCH_SIZE = 10_000

#: How many months of ``sync.sync_payloads`` partitions to keep ahead. Months,
#: not days: one partition covers a month, so "3" is a quarter of runway.
PAYLOAD_MONTHS_AHEAD = 3


@dataclass(frozen=True, slots=True)
class PartitionedTable:
    """Everything retention needs to know about one partitioned history table."""

    qualified: str                       # 'zoho_sync_events' | 'sync.sync_payloads'
    ts_column: str                       # partition key / age column
    pk: tuple[str, ...]                  # identifying tuple for the batched DELETE
    period: Literal["daily", "monthly"]
    class_column: str                    # column whose value maps to a policy class
    class_map: Mapping[str, str] = field(default_factory=dict)

    @property
    def schema(self) -> str:
        return self.qualified.split(".")[0] if "." in self.qualified else "public"

    @property
    def bare(self) -> str:
        """Relation name without schema — what ``pg_class.relname`` holds."""
        return self.qualified.split(".")[-1]

    @property
    def suffix_format(self) -> str:
        return "%Y%m%d" if self.period == "daily" else "%Y%m"

    def partition_name(self, moment: date) -> str:
        """Bare partition name (unqualified, like the parent's own name)."""
        return f"{self.bare}_p{moment:{self.suffix_format}}"

    def qualify(self, partition: str) -> str:
        return f"{self.schema}.{partition}" if self.schema != "public" else partition

    def period_start(self, moment: date) -> date:
        return moment if self.period == "daily" else moment.replace(day=1)

    def bounds(self, moment: date) -> tuple[datetime, datetime]:
        """Half-open [start, end) of the period containing ``moment``."""
        start_date = self.period_start(moment)
        if self.period == "daily":
            end_date = start_date + timedelta(days=1)
        else:
            index = start_date.year * 12 + start_date.month      # already +1 month
            end_date = date(index // 12, index % 12 + 1, 1)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(end_date, datetime.min.time(), tzinfo=UTC)
        return start, end

    def advance(self, anchor: date, steps: int) -> date:
        """``steps`` periods after the period containing ``anchor``."""
        start = self.period_start(anchor)
        if self.period == "daily":
            return start + timedelta(days=steps)
        index = start.year * 12 + (start.month - 1) + steps
        return date(index // 12, index % 12 + 1, 1)

    def last_day_held(self, partition_start: date) -> date:
        """The newest date a partition can hold — what its age must be measured
        from. For a daily partition that is the day itself (so behaviour is
        unchanged); for a monthly one it is the month's last day, without which
        a month partition would be dropped while still holding fresh rows."""
        if self.period == "daily":
            return partition_start
        _, end = self.bounds(partition_start)
        return end.date() - timedelta(days=1)

    def default_ahead(self) -> int:
        if self.period == "daily":
            return settings.ZOHO_SYNC_EVENTS_PARTITION_DAYS_AHEAD
        return PAYLOAD_MONTHS_AHEAD


EVENTS = PartitionedTable(
    qualified=EVENTS_TABLE, ts_column="occurred_at", pk=("id", "occurred_at"),
    period="daily", class_column="event_type", class_map=EVENT_CLASS,
)
PAYLOADS = PartitionedTable(
    qualified=PAYLOADS_TABLE, ts_column="synced_at", pk=("id", "synced_at"),
    period="monthly", class_column="outcome", class_map=PAYLOAD_CLASS,
)
#: Every partitioned history table the nightly job maintains.
MAINTAINED: tuple[PartitionedTable, ...] = (EVENTS, PAYLOADS)


@dataclass(frozen=True, slots=True)
class Policy:
    module: str
    event_class: str
    keep_days: int

    @property
    def specificity(self) -> int:
        return (2 if self.module != "*" else 0) + (1 if self.event_class != "*" else 0)


async def load_policies(db: AsyncSession, table_name: str) -> list[Policy]:
    rows = (await db.scalars(
        select(ZohoRetentionPolicy).where(
            ZohoRetentionPolicy.table_name == table_name, ZohoRetentionPolicy.enabled.is_(True)
        )
    )).all()
    return sorted(
        (Policy(r.module, r.event_class, r.keep_days) for r in rows),
        key=lambda p: -p.specificity,
    )


def effective_keep_days(
    policies: list[Policy], *, module: str, event_type: str, table: PartitionedTable = EVENTS
) -> int | None:
    """Most specific policy wins (pure — mirrors the SQL CASE below).

    ``event_type`` is the value of the table's ``class_column``: an event type
    for ``zoho_sync_events``, an outcome for ``sync.sync_payloads``.
    """
    event_class = table.class_map.get(event_type, "*")
    for policy in policies:                         # already most-specific first
        if policy.module not in ("*", module):
            continue
        if policy.event_class not in ("*", event_class):
            continue
        return policy.keep_days
    return None


def _keep_case_sql(
    policies: list[Policy], table: PartitionedTable = EVENTS
) -> tuple[str, dict[str, Any]]:
    """SQL expression giving each row's keep-days (NULL = keep forever)."""
    classes: dict[str, list[str]] = {}
    for value, cls in table.class_map.items():
        classes.setdefault(cls, []).append(value)

    params: dict[str, Any] = {}
    whens: list[str] = []
    for i, policy in enumerate(policies):
        conditions = []
        if policy.module != "*":
            params[f"m{i}"] = policy.module
            conditions.append(f"module = :m{i}")
        if policy.event_class != "*":
            params[f"c{i}"] = classes.get(policy.event_class, ["__none__"])
            conditions.append(f"{table.class_column} = ANY(:c{i})")
        params[f"k{i}"] = policy.keep_days
        # explicit cast: a bare bind inside CASE is typed as text by asyncpg (ERRORS E14)
        whens.append(f"WHEN {' AND '.join(conditions) or 'TRUE'} THEN CAST(:k{i} AS integer)")
    return ("CASE " + " ".join(whens) + " END") if whens else "NULL", params


# ── partitions ──────────────────────────────────────────────────────────────

def partition_name(moment: date, table: PartitionedTable = EVENTS) -> str:
    return table.partition_name(moment)


async def ensure_partitions(
    db: AsyncSession,
    *,
    today: date | None = None,
    days_ahead: int | None = None,
    table: PartitionedTable = EVENTS,
) -> list[str]:
    """Create partitions from today to ``days_ahead`` periods out. Idempotent.

    ``days_ahead`` counts *periods*: days for a daily table, months for a
    monthly one (the name is kept for the existing callers and tests).
    """
    today = today or datetime.now(UTC).date()
    ahead = table.default_ahead() if days_ahead is None else days_ahead
    created: list[str] = []
    for offset in range(0, ahead + 1):
        moment = table.advance(today, offset)
        name = table.partition_name(moment)
        exists = await db.scalar(
            text("SELECT to_regclass(:n) IS NOT NULL"), {"n": f"{table.schema}.{name}"}
        )
        if exists:
            continue
        start, end = table.bounds(moment)
        try:
            async with db.begin_nested():
                await db.execute(text(
                    f"CREATE TABLE {table.qualify(name)} PARTITION OF {table.qualified} "
                    f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
                ))
            created.append(name)
        except Exception as exc:  # noqa: BLE001 — rows for that period already sit in DEFAULT
            logger.warning("zoho.retention.partition_create_failed", table=table.qualified,
                           partition=name, error=str(exc)[:300])
    await db.commit()
    if created:
        logger.info("zoho.retention.partitions_created", table=table.qualified, partitions=created)
    return created


async def list_partitions(
    db: AsyncSession, table: PartitionedTable = EVENTS
) -> list[tuple[str, date]]:
    """Every dated partition of ``table``, as ``(name, period start)``.

    The DEFAULT partition has no date suffix and is deliberately skipped — it is
    never dropped, because it is where rows land when a period partition is
    missing.
    """
    rows = (await db.execute(text(
        """
        SELECT c.relname FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        JOIN pg_namespace n ON n.oid = p.relnamespace
        WHERE p.relname = :parent AND n.nspname = :schema
        """
    ), {"parent": table.bare, "schema": table.schema})).scalars().all()
    expected = 8 if table.period == "daily" else 6
    result = []
    for name in rows:
        suffix = name.rsplit("_p", 1)[-1]
        if len(suffix) == expected and suffix.isdigit():
            result.append((name, datetime.strptime(suffix, table.suffix_format).date()))
    return sorted(result, key=lambda item: item[1])


async def drop_expired_partitions(
    db: AsyncSession,
    policies: list[Policy],
    *,
    today: date | None = None,
    table: PartitionedTable = EVENTS,
) -> list[str]:
    """Drop partitions that can no longer hold anything a policy keeps.

    A partition is dropped when it is older than the LONGEST policy (nothing in
    it can be kept), or older than the SHORTEST policy and already empty after
    :func:`purge_events`. The second rule matters: one long-lived class (e.g.
    approvals kept 7 years) would otherwise pin every partition for 7 years and
    turn all retention into row-by-row deletes (ERRORS E15). Run the purge first.

    Age is measured from the NEWEST date a partition can hold, not its start —
    otherwise a monthly partition would be dropped while its last days are still
    inside the shortest keep. For daily partitions the two are the same.
    """
    if not policies:
        return []
    today = today or datetime.now(UTC).date()
    longest = max(p.keep_days for p in policies)
    shortest = min(p.keep_days for p in policies)
    dropped = []
    for name, start in await list_partitions(db, table):
        age = (today - table.last_day_held(start)).days
        if age <= shortest:
            continue
        qualified = table.qualify(name)
        empty = not await db.scalar(text(f"SELECT EXISTS (SELECT 1 FROM {qualified})"))
        if age > longest or empty:
            await db.execute(text(f"DROP TABLE IF EXISTS {qualified}"))
            dropped.append(name)
    await db.commit()
    if dropped:
        logger.info("zoho.retention.partitions_dropped", table=table.qualified, partitions=dropped,
                    shortest_keep_days=shortest, longest_keep_days=longest)
    return dropped


# ── row purges ──────────────────────────────────────────────────────────────

async def purge_events(
    db: AsyncSession,
    policies: list[Policy],
    *,
    time_budget_s: float = 60.0,
    table: PartitionedTable = EVENTS,
) -> int:
    """Batched deletes applying the most specific policy per row."""
    if not policies:
        return 0
    case_sql, params = _keep_case_sql(policies, table)
    pk = ", ".join(table.pk)
    deleted = 0
    started = time.monotonic()
    while time.monotonic() - started < time_budget_s:
        result = await db.execute(text(
            f"""
            DELETE FROM {table.qualified}
            WHERE ({pk}) IN (
                SELECT {pk} FROM {table.qualified}
                WHERE ({case_sql}) IS NOT NULL
                  AND {table.ts_column} < now() - make_interval(days => ({case_sql}))
                LIMIT {BATCH_SIZE}
            )
            """
        ), params)
        await db.commit()
        deleted += result.rowcount or 0
        if (result.rowcount or 0) < BATCH_SIZE:
            break
    return deleted


async def purge_runs(db: AsyncSession, keep_days: int | None) -> int:
    if keep_days is None:
        return 0
    result = await db.execute(text(
        "DELETE FROM zoho_sync_runs WHERE status <> :running "
        "AND started_at < now() - make_interval(days => :keep)"
    ), {"running": RunStatus.RUNNING, "keep": keep_days})
    await db.commit()
    return result.rowcount or 0


async def purge_quota_days(db: AsyncSession, keep_days: int | None) -> int:
    if keep_days is None:
        return 0
    cutoff = (datetime.now(UTC).date() - timedelta(days=keep_days)).strftime("%Y%m%d")
    result = await db.execute(text("DELETE FROM zoho_quota_days WHERE day < :cutoff"),
                              {"cutoff": cutoff})
    await db.commit()
    return result.rowcount or 0


async def run_maintenance(db: AsyncSession) -> dict[str, Any]:
    """The nightly job: partitions ahead, expired partitions dropped, purges.

    Every maintained table runs the same three steps. A table with no policy
    rows is skipped by the functions themselves (no policies = nothing to do),
    so adding a table here before its policies are seeded is harmless.
    """
    created: dict[str, list[str]] = {}
    dropped: dict[str, list[str]] = {}
    purged: dict[str, int] = {}
    for table in MAINTAINED:
        created[table.qualified] = await ensure_partitions(db, table=table)
        policies = await load_policies(db, table.qualified)
        # Purge first: it is what empties old partitions so they can be dropped.
        purged[table.qualified] = await purge_events(db, policies, table=table)
        dropped[table.qualified] = await drop_expired_partitions(db, policies, table=table)

    run_policies = await load_policies(db, "zoho_sync_runs")
    quota_policies = await load_policies(db, "zoho_quota_days")
    runs_deleted = await purge_runs(db, run_policies[0].keep_days if run_policies else None)
    quota_deleted = await purge_quota_days(db, quota_policies[0].keep_days if quota_policies else None)

    summary = {
        "partitions_created": created[EVENTS_TABLE],
        "partitions_dropped": dropped[EVENTS_TABLE],
        "events_deleted": purged[EVENTS_TABLE],
        "payload_partitions_created": created[PAYLOADS_TABLE],
        "payload_partitions_dropped": dropped[PAYLOADS_TABLE],
        "payloads_deleted": purged[PAYLOADS_TABLE],
        "runs_deleted": runs_deleted,
        "quota_days_deleted": quota_deleted,
    }
    logger.info("zoho.retention.completed", **summary)
    return summary


__all__ = [
    "EVENTS",
    "MAINTAINED",
    "PAYLOADS",
    "PartitionedTable",
    "Policy",
    "drop_expired_partitions",
    "effective_keep_days",
    "ensure_partitions",
    "list_partitions",
    "load_policies",
    "partition_name",
    "purge_events",
    "purge_quota_days",
    "purge_runs",
    "run_maintenance",
]
