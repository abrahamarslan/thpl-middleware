"""Retention policies, partitions and purges (real Postgres)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text

from app.modules.zoho.control.models import ZohoSyncEvent
from app.modules.zoho.control.retention import (
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
    [
        Policy("*", "*", 90),
        Policy("*", "success", 30),
        Policy("*", "approval", 2555),
        Policy("invoices", "success", 60),
    ],
    key=lambda p: -p.specificity,
)


def test_most_specific_policy_wins():
    assert effective_keep_days(POLICIES, module="invoices", event_type="updated") == 60
    assert effective_keep_days(POLICIES, module="contacts", event_type="updated") == 30
    assert effective_keep_days(POLICIES, module="contacts", event_type="approval_approved") == 2555
    assert effective_keep_days(POLICIES, module="contacts", event_type="mystery") == 90
    assert effective_keep_days([], module="contacts", event_type="updated") is None


async def test_migration_seeds_default_policies(db):
    policies = await load_policies(db, "zoho_sync_events")
    scopes = {(p.module, p.event_class): p.keep_days for p in policies}
    assert scopes[("*", "*")] == 90 and scopes[("*", "success")] == 30
    assert scopes[("*", "approval")] >= 365


async def test_partitions_are_created_ahead_and_idempotent(db):
    today = datetime.now(UTC).date()
    created = await ensure_partitions(db, today=today, days_ahead=2)
    again = await ensure_partitions(db, today=today, days_ahead=2)
    names = {name for name, _ in await list_partitions(db)}
    assert {partition_name(today + timedelta(days=i)) for i in range(3)} <= names
    assert again == [] and len(created) <= 3


async def _old_partition(db, day: date) -> str:
    name = partition_name(day)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    await db.execute(text(
        f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF zoho_sync_events "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{(start + timedelta(days=1)).isoformat()}')"
    ))
    await db.commit()
    return name


async def test_empty_partitions_past_the_shortest_policy_are_dropped(db):
    empty = await _old_partition(db, date(2020, 1, 1))
    dropped = await drop_expired_partitions(db, POLICIES)
    assert empty in dropped


async def test_partitions_holding_kept_rows_survive(db):
    """An approval event (kept 2555 days) pins its partition; the partition
    goes once it is older than the longest policy."""
    recent_day = (datetime.now(UTC) - timedelta(days=400)).date()
    kept = await _old_partition(db, recent_day)
    db.add(ZohoSyncEvent(module="contacts", event_type="approval_approved", direction="push",
                         occurred_at=datetime(recent_day.year, recent_day.month, recent_day.day, 12, tzinfo=UTC)))
    await db.commit()

    assert kept not in await drop_expired_partitions(db, POLICIES)
    ancient = await _old_partition(db, date(2015, 1, 1))
    assert ancient in await drop_expired_partitions(db, POLICIES)


async def _event(db, *, module, event_type, days_ago):
    db.add(ZohoSyncEvent(
        module=module, event_type=event_type, direction="pull",
        occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
    ))


async def test_purge_applies_each_rows_own_policy(db):
    await _event(db, module="contacts", event_type="updated", days_ago=45)          # 30 d → purge
    await _event(db, module="invoices", event_type="updated", days_ago=45)          # 60 d → keep
    await _event(db, module="contacts", event_type="approval_approved", days_ago=400)  # 2555 d → keep
    await _event(db, module="contacts", event_type="record_error", days_ago=120)    # 90 d (*) → purge
    await _event(db, module="contacts", event_type="updated", days_ago=1)           # recent → keep
    await db.commit()

    deleted = await purge_events(db, POLICIES)
    assert deleted == 2
    remaining = await db.scalar(select(func.count()).select_from(ZohoSyncEvent))
    assert remaining == 3
