"""Retention for ``sync.sync_payloads``: monthly partitions, in another schema.

The generalised ``PartitionedTable`` has to get three things right that the
daily events table never exercised: a schema-qualified name, a month-long
period, and measuring a partition's age from the newest row it can hold rather
than from its start. The last one is a real dropped-data bug if it is wrong —
a February partition is 47 days "old" on 20 March by its start date, but its
last rows are only 20 days old.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text

from app.core.conf import settings
from app.modules.sync.models import SyncOutcome, SyncPayload
from app.modules.tenants.model import Tenant
from app.modules.zoho.control.retention import (
    EVENTS,
    MAINTAINED,
    PAYLOADS,
    PartitionedTable,
    Policy,
    drop_expired_partitions,
    effective_keep_days,
    ensure_partitions,
    list_partitions,
    load_policies,
    partition_name,
    purge_events,
)

POLICIES = sorted(
    [Policy("*", "*", 30), Policy("*", "failure", 365), Policy("invoices", "success", 90)],
    key=lambda p: -p.specificity,
)


# ── the descriptor (pure) ───────────────────────────────────────────────────

def test_the_events_descriptor_is_unchanged_behaviour():
    day = date(2026, 9, 21)
    assert EVENTS.schema == "public" and EVENTS.bare == "zoho_sync_events"
    assert partition_name(day) == "zoho_sync_events_p20260921"
    assert EVENTS.bounds(day) == (datetime(2026, 9, 21, tzinfo=UTC), datetime(2026, 9, 22, tzinfo=UTC))
    assert EVENTS.advance(day, 3) == date(2026, 9, 24)
    # A daily partition's newest row is its own day — the old age calculation.
    assert EVENTS.last_day_held(day) == day


def test_the_payloads_descriptor_is_monthly_and_schema_qualified():
    assert PAYLOADS.schema == "sync" and PAYLOADS.bare == "sync_payloads"
    assert PAYLOADS.qualify("sync_payloads_p202609") == "sync.sync_payloads_p202609"
    assert partition_name(date(2026, 9, 21), PAYLOADS) == "sync_payloads_p202609"
    assert PAYLOADS.bounds(date(2026, 9, 21)) == (
        datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
    )


def test_month_arithmetic_rolls_over_the_year():
    assert PAYLOADS.advance(date(2026, 12, 15), 1) == date(2027, 1, 1)
    assert PAYLOADS.advance(date(2026, 11, 1), 3) == date(2027, 2, 1)
    assert PAYLOADS.bounds(date(2026, 12, 3))[1] == datetime(2027, 1, 1, tzinfo=UTC)
    assert PAYLOADS.last_day_held(date(2026, 2, 1)) == date(2026, 2, 28)
    assert PAYLOADS.last_day_held(date(2024, 2, 1)) == date(2024, 2, 29)   # leap year


def test_outcomes_map_to_policy_classes():
    assert effective_keep_days(POLICIES, module="currencies",
                               event_type=SyncOutcome.UPDATED, table=PAYLOADS) == 30
    assert effective_keep_days(POLICIES, module="currencies",
                               event_type=SyncOutcome.TOMBSTONED, table=PAYLOADS) == 365
    assert effective_keep_days(POLICIES, module="invoices",
                               event_type=SyncOutcome.INSERTED, table=PAYLOADS) == 90


# ── partitions (real Postgres) ──────────────────────────────────────────────

async def test_the_migration_seeds_payload_policies(db):
    policies = await load_policies(db, "sync.sync_payloads")
    scopes = {(p.module, p.event_class): p.keep_days for p in policies}
    assert scopes[("*", "*")] == 180 and scopes[("*", "failure")] == 365


async def test_monthly_partitions_are_created_ahead_and_idempotent(db):
    today = date(2026, 9, 15)
    created = await ensure_partitions(db, today=today, days_ahead=2, table=PAYLOADS)
    again = await ensure_partitions(db, today=today, days_ahead=2, table=PAYLOADS)
    names = {name for name, _ in await list_partitions(db, PAYLOADS)}

    assert {"sync_payloads_p202609", "sync_payloads_p202610", "sync_payloads_p202611"} <= names
    assert again == [], "creating the same months twice must be a no-op"
    assert all(name.startswith("sync_payloads_p") for name in created)


async def test_the_default_partition_is_never_listed_for_dropping(db):
    names = {name for name, _ in await list_partitions(db, PAYLOADS)}
    assert "sync_payloads_default" not in names, (
        "DEFAULT holds rows whose month partition is missing — dropping it loses data"
    )


async def _month_partition(db, month: date) -> str:
    name = PAYLOADS.partition_name(month)
    start, end = PAYLOADS.bounds(month)
    await db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {PAYLOADS.qualify(name)} PARTITION OF sync.sync_payloads "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
    ))
    await db.commit()
    return name


async def _drop(db, name: str) -> None:
    await db.execute(text(f"DROP TABLE IF EXISTS {PAYLOADS.qualify(name)}"))
    await db.commit()


async def test_an_expired_empty_month_is_dropped(db):
    old = await _month_partition(db, date(2019, 3, 1))
    dropped = await drop_expired_partitions(db, POLICIES, table=PAYLOADS)
    assert old in dropped


async def test_a_month_is_not_dropped_while_its_last_days_are_still_kept(db):
    """The age-from-last-day rule. February's partition starts 47 days before
    20 March but ends only 20 days before it — inside a 30-day keep."""
    february = await _month_partition(db, date(2026, 2, 1))
    try:
        dropped = await drop_expired_partitions(
            db, POLICIES, today=date(2026, 3, 20), table=PAYLOADS
        )
        assert february not in dropped, (
            "dropped a partition still holding rows inside the shortest keep — "
            "age must be measured from the month's last day, not its first"
        )
        # One month later the whole month is outside the keep and it goes.
        later = await drop_expired_partitions(
            db, POLICIES, today=date(2026, 4, 30), table=PAYLOADS
        )
        assert february in later
    finally:
        await _drop(db, february)


# ── purges ──────────────────────────────────────────────────────────────────

async def _payload(db, *, module: str, outcome: str, days_ago: int) -> None:
    tenant = await db.scalar(
        select(Tenant).where(Tenant.tenant_code == settings.DEFAULT_TENANT_CODE)
    )
    db.add(SyncPayload(
        tenant_id=tenant.id, sync_record_id=1, source_system="zoho", module=module,
        external_id="X", outcome=outcome, synced_at=datetime.now(UTC) - timedelta(days=days_ago),
    ))


async def test_purge_applies_each_payloads_own_policy(db):
    await _payload(db, module="currencies", outcome=SyncOutcome.UPDATED, days_ago=45)      # 30 d → go
    await _payload(db, module="invoices", outcome=SyncOutcome.INSERTED, days_ago=45)       # 90 d → stay
    await _payload(db, module="currencies", outcome=SyncOutcome.TOMBSTONED, days_ago=200)  # 365 d → stay
    await _payload(db, module="currencies", outcome=SyncOutcome.UPDATED, days_ago=1)       # recent → stay
    await db.commit()

    deleted = await purge_events(db, POLICIES, table=PAYLOADS)
    assert deleted == 1
    assert await db.scalar(select(func.count()).select_from(SyncPayload)) == 3


async def test_both_history_tables_are_maintained(db):
    """A table added to MAINTAINED but not to run_maintenance is a table that
    silently stops being cleaned up."""
    assert {table.qualified for table in MAINTAINED} == {"zoho_sync_events", "sync.sync_payloads"}
    assert all(isinstance(table, PartitionedTable) for table in MAINTAINED)
