"""Run leases and fenced cursors (real Postgres)."""

import pytest
from sqlalchemy import select, text

from app.modules.zoho.control.models import RunStatus, ZohoSyncRun
from app.modules.zoho.control.runs import (
    CursorFenced,
    acquire_run,
    advance_cursor,
    claim_cursor,
    finish_run,
    heartbeat,
    load_cursor,
    reap_expired,
)


async def test_only_one_run_per_lane(db):
    first = await acquire_run(db, module="contacts", lane="scheduled", trigger="test", owner="w1")
    second = await acquire_run(db, module="contacts", lane="scheduled", trigger="test", owner="w2")
    other_lane = await acquire_run(db, module="contacts", lane="weekly_full", trigger="test", owner="w2")

    assert first is not None
    assert second is None                          # the DB index refused it
    assert other_lane is not None                  # lanes are independent


async def test_expired_lease_is_abandoned_and_taken_over(db):
    dead = await acquire_run(db, module="items", lane="scheduled", trigger="test", owner="dead-worker")
    await db.execute(text("UPDATE zoho_sync_runs SET lease_expires_at = now() - interval '1 minute' "
                          "WHERE id = :id"), {"id": dead.id})
    await db.commit()

    fresh = await acquire_run(db, module="items", lane="scheduled", trigger="test", owner="w2")
    assert fresh is not None and fresh.id != dead.id
    status = await db.scalar(select(ZohoSyncRun.status).where(ZohoSyncRun.id == dead.id))
    assert status == RunStatus.ABANDONED


async def test_zombie_cannot_heartbeat_or_finish_after_takeover(db):
    zombie = await acquire_run(db, module="items", lane="scheduled", trigger="test", owner="zombie")
    await db.execute(text("UPDATE zoho_sync_runs SET lease_expires_at = now() - interval '1 minute' "
                          "WHERE id = :id"), {"id": zombie.id})
    await db.commit()
    await reap_expired(db)

    assert await heartbeat(db, zombie) is False
    await finish_run(db, zombie, status=RunStatus.SUCCEEDED)          # silently fenced
    status = await db.scalar(select(ZohoSyncRun.status).where(ZohoSyncRun.id == zombie.id))
    assert status == RunStatus.ABANDONED


async def test_finish_records_counters_and_errors(db):
    from app.modules.zoho.core.errors import ZohoTransientError

    run = await acquire_run(db, module="items", lane="manual", trigger="test", owner="w1")
    await finish_run(db, run, status=RunStatus.FAILED, counters={"listed": 5, "created": 2},
                     duration_ms=1200, error=ZohoTransientError("Zoho 502 for item 982000000567114"))
    row = await db.get(ZohoSyncRun, run.id)
    await db.refresh(row)
    assert row.status == RunStatus.FAILED and row.listed == 5 and row.created == 2
    assert row.error_category == "transient" and len(row.error_fingerprint) == 16
    assert row.finished_at is not None


async def test_cursor_writes_are_fenced_to_the_owning_run(db):
    first = await acquire_run(db, module="items", lane="scheduled", trigger="test", owner="w1")
    await claim_cursor(db, first)
    await advance_cursor(db, first, next_page=3)
    await db.commit()

    await finish_run(db, first, status=RunStatus.SUCCEEDED)
    second = await acquire_run(db, module="items", lane="scheduled", trigger="test", owner="w2")
    await claim_cursor(db, second)
    await db.commit()

    with pytest.raises(CursorFenced):
        await advance_cursor(db, first, next_page=99)             # the old run lost ownership
    await db.rollback()

    cursor = await load_cursor(db, module="items", lane="scheduled")
    assert cursor.next_page == 3 and cursor.owner_run_id == second.id
