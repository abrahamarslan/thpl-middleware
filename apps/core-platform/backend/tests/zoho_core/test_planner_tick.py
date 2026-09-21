"""A real planner tick against Postgres + Redis (Celery not involved)."""

import json

from sqlalchemy import select, text

from app.core.conf import settings
from app.modules.zoho.control import planner
from app.modules.zoho.control.models import ZohoQuotaDay
from app.modules.zoho.control.runs import acquire_run
from app.modules.zoho.control.switches import zoho_switches


async def test_tick_enqueues_due_lanes_persists_quota_and_publishes_health(db, redis_available, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_PLANNER_MAX_CONCURRENT_RUNS", 10)   # every registered module due
    zoho_switches.invalidate()
    enqueued: list[tuple[str, str, str | None]] = []

    summary = await planner.tick(db, enqueue=lambda m, lane, mode: enqueued.append((m, lane, mode)))

    # organizations, currencies and taxes are FULL-strategy modules → scheduled lane only
    for module in ("organizations", "currencies", "taxes"):
        assert (module, planner.LANE_SCHEDULED, None) in enqueued
    assert all(lane != planner.LANE_WEEKLY_FULL for _, lane, _ in enqueued)

    quota = (await db.scalars(select(ZohoQuotaDay))).all()
    assert len(quota) == 1 and quota[0].daily_hard_limit == settings.ZOHO_DAILY_HARD_LIMIT

    health = json.loads(await redis_available.get(planner.HEALTH_KEY))
    assert health["planner"]["enqueued"] == summary["enqueued"]
    assert "governor" in health and "token" in health


async def test_tick_skips_a_running_lane_and_reaps_dead_ones(db, redis_available, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_PLANNER_MAX_CONCURRENT_RUNS", 10)
    zoho_switches.invalidate()
    live = await acquire_run(db, module="organizations", lane=planner.LANE_SCHEDULED, trigger="test", owner="w1")
    # a long-running run: its lane is due again, but must not be enqueued twice
    await db.execute(text("UPDATE zoho_sync_runs SET started_at = now() - interval '1 day' WHERE id = :id"),
                     {"id": live.id})
    await db.commit()
    enqueued = []
    summary = await planner.tick(db, enqueue=lambda *a: enqueued.append(a))
    assert all(m != "organizations" for m, _, _ in enqueued)
    assert summary["skipped"]["organizations/scheduled"] == "lane_running"

    await db.execute(text("UPDATE zoho_sync_runs SET lease_expires_at = now() - interval '1 minute' "
                          "WHERE id = :id"), {"id": live.id})
    await db.commit()
    enqueued.clear()
    summary = await planner.tick(db, enqueue=lambda *a: enqueued.append(a))
    assert summary["reaped"] == 1
    assert ("organizations", planner.LANE_SCHEDULED, None) in enqueued    # the dead run's lane is due again


async def test_planner_can_be_disabled(db, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_PLANNER_ENABLED", False)
    enqueued = []
    assert await planner.tick(db, enqueue=lambda *a: enqueued.append(a)) == {"enabled": False}
    assert enqueued == []


async def test_history_turns_yielded_runs_into_continuations(db):
    from datetime import UTC, datetime, timedelta

    from app.modules.zoho.control.models import RunStatus, ZohoSyncRun

    now = datetime.now(UTC)
    db.add_all([
        ZohoSyncRun(module="organizations", lane="weekly_full", mode="full", trigger="planner",
                    status=RunStatus.YIELDED, stop_reason="budget:max_run_seconds",
                    started_at=now - timedelta(minutes=5), finished_at=now - timedelta(minutes=1)),
        ZohoSyncRun(module="organizations", lane="scheduled", trigger="planner",
                    status=RunStatus.YIELDED, stop_reason="governor:conserve",
                    started_at=now - timedelta(minutes=3), finished_at=now - timedelta(minutes=2)),
        # a yield later superseded by a success is NOT continued
        ZohoSyncRun(module="organizations", lane="manual", mode="index", trigger="api",
                    status=RunStatus.YIELDED, stop_reason="budget:max_pages",
                    started_at=now - timedelta(minutes=9), finished_at=now - timedelta(minutes=8)),
        ZohoSyncRun(module="organizations", lane="manual", mode="index", trigger="planner",
                    status=RunStatus.SUCCEEDED,
                    started_at=now - timedelta(minutes=7), finished_at=now - timedelta(minutes=6)),
    ])
    await db.commit()

    history = await planner._run_history(db, now=now)
    conts = history.continuations
    assert set(conts) == {("organizations", "weekly_full"), ("organizations", "scheduled")}
    assert conts[("organizations", "weekly_full")].due_at <= now                      # budget: at once
    assert conts[("organizations", "scheduled")].due_at > now                         # refusal: backoff
    assert conts[("organizations", "weekly_full")].mode == "full"


async def test_governor_is_reseeded_after_redis_loses_the_day(db, redis_available):
    from app.modules.zoho.core.governor import zoho_governor

    await zoho_governor.reset_day()
    day = zoho_governor.current_day()
    db.add(ZohoQuotaDay(pool=zoho_governor.config.pool, day=day.key, used=31_000, used_background=20_000))
    await db.commit()

    assert await planner.reseed_governor(db) is True
    snapshot = await zoho_governor.snapshot()
    assert snapshot["used"] == 31_000 and snapshot["used_background"] == 20_000
    assert await planner.reseed_governor(db) is False              # raise-only: nothing to do now
    await zoho_governor.reset_day()


async def test_write_pressure_probe_is_quiet_on_a_healthy_stack(db, redis_available):
    assert await planner.write_pressure(db) is None
