"""Governor tests — the gate that must never let us exceed Zoho's limits.

These run against the scratch Redis (see tests/conftest.py) and skip cleanly
when it is absent. Each test uses its own pool name so parallel runs and
leftovers can never interfere.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.zoho.core.errors import (
    ZohoBudgetDeferred,
    ZohoQuotaExhaustedError,
    ZohoRateLimitedError,
)
from app.modules.zoho.core.governor import (
    Governor,
    GovernorConfig,
    GovernorState,
    Priority,
)
from app.modules.zoho.core.pacing import PacingCurve


def make_config(**overrides) -> GovernorConfig:
    base = dict(
        pool=f"test{uuid.uuid4().hex[:8]}",
        org_id=f"org{uuid.uuid4().hex[:8]}",
        contract_daily_limit=45_000,
        daily_hard_limit=1_000,
        soft_pct=0.80,
        essential_pct=0.90,
        hard_pct=0.95,
        reserve_calls=20,
        rate_per_minute=60,
        rate_burst=10,
        concurrency_limit=3,
        pacing_curve=PacingCurve.NONE,
        lease_ttl_seconds=5.0,
    )
    base.update(overrides)
    return GovernorConfig(**base)


@pytest.fixture
async def governor(redis_available):
    gov = Governor(config=make_config(), redis=redis_available)
    yield gov
    await gov.reset_day()


async def spend(gov: Governor, count: int, priority: Priority = Priority.INCREMENTAL) -> None:
    """Simulate `count` calls that actually went out (small counts only —
    every call takes a real token from the minute bucket)."""
    for _ in range(count):
        lease = await gov.acquire(priority)
        lease.mark_sent()
        await gov.release(lease)


async def seed_used(gov: Governor, used: int) -> None:
    """Fast-forward the day counter without burning minute-bucket tokens."""
    day = gov.current_day()
    await gov._redis.hset(gov._day_key(day), mapping={"used": used, "reserved": 0})
    await gov._redis.expire(gov._day_key(day), day.ttl_seconds)


# ── admission & accounting ──────────────────────────────────────────────────

async def test_acquire_reserves_and_release_commits(governor):
    lease = await governor.acquire(Priority.PUSH, module="invoices")
    snap = await governor.snapshot()
    assert snap["reserved"] == 1 and snap["used"] == 0 and snap["inflight"] == 1

    lease.mark_sent()
    await governor.release(lease)

    snap = await governor.snapshot()
    assert snap["used"] == 1 and snap["reserved"] == 0 and snap["inflight"] == 0
    assert snap["remaining"] == governor.config.daily_hard_limit - 1


async def test_unsent_request_refunds_the_reservation(governor):
    lease = await governor.acquire(Priority.PUSH)
    await governor.release(lease)                 # never marked sent
    snap = await governor.snapshot()
    assert snap["used"] == 0 and snap["reserved"] == 0


async def test_release_is_idempotent(governor):
    lease = await governor.acquire(Priority.REFRESH)
    lease.mark_sent()
    await governor.release(lease)
    await governor.release(lease)                 # retried settle (redis-py may retry)
    assert (await governor.snapshot())["used"] == 1


async def test_slot_context_manager_settles_on_exit(governor):
    async with governor.slot(Priority.INTERACTIVE) as lease:
        lease.mark_sent()
    assert (await governor.snapshot())["used"] == 1

    with pytest.raises(RuntimeError):
        async with governor.slot(Priority.INTERACTIVE) as lease:
            lease.mark_sent()
            raise RuntimeError("boom")
    snap = await governor.snapshot()
    assert snap["used"] == 2 and snap["reserved"] == 0    # still settled


# ── daily ceiling & states ──────────────────────────────────────────────────

async def test_states_escalate_as_the_day_fills(governor):
    cfg = governor.config

    await seed_used(governor, cfg.soft_threshold)
    assert (await governor.snapshot())["state"] == GovernorState.CONSERVE
    # reconcile is the first class to stop
    with pytest.raises(ZohoBudgetDeferred) as excinfo:
        await governor.acquire(Priority.RECONCILE)
    assert "conserve" in excinfo.value.reason
    async with governor.slot(Priority.INCREMENTAL) as lease:    # still running
        lease.mark_sent()

    await seed_used(governor, cfg.essential_threshold)
    assert (await governor.snapshot())["state"] == GovernorState.ESSENTIAL
    with pytest.raises(ZohoBudgetDeferred):
        await governor.acquire(Priority.INCREMENTAL)
    # push and refresh still work — user intent must keep flowing
    async with governor.slot(Priority.PUSH) as lease:
        lease.mark_sent()

    await seed_used(governor, cfg.hard_threshold)
    assert (await governor.snapshot())["state"] == GovernorState.RESERVED_ONLY
    with pytest.raises(ZohoBudgetDeferred):
        await governor.acquire(Priority.PUSH)
    # interactive/critical may use the reserve above the hard threshold
    async with governor.slot(Priority.INTERACTIVE) as lease:
        lease.mark_sent()


async def test_daily_ceiling_is_never_exceeded(governor):
    cfg = governor.config
    await seed_used(governor, cfg.daily_hard_limit)
    snap = await governor.snapshot()
    assert snap["used"] == cfg.daily_hard_limit
    assert snap["state"] == GovernorState.EXHAUSTED
    assert snap["remaining"] == 0

    for priority in (Priority.INTERACTIVE, Priority.PUSH, Priority.RECONCILE):
        with pytest.raises(ZohoQuotaExhaustedError) as excinfo:
            await governor.acquire(priority)
        assert excinfo.value.resets_at


async def test_zoho_code_45_overrides_our_counter(governor):
    await governor.mark_quota_exhausted(reason="zoho_code_45")
    snap = await governor.snapshot()
    assert snap["state"] == GovernorState.EXHAUSTED and snap["used"] == 0
    with pytest.raises(ZohoQuotaExhaustedError):
        await governor.acquire(Priority.INTERACTIVE)


async def test_new_quota_day_resumes_automatically(governor):
    await seed_used(governor, governor.config.daily_hard_limit)
    with pytest.raises(ZohoQuotaExhaustedError):
        await governor.acquire(Priority.RECONCILE)

    tomorrow = datetime.now(UTC) + timedelta(days=1)
    lease = await governor.acquire(Priority.RECONCILE, now=tomorrow)   # new day key
    assert lease.day_key != governor.current_day().key
    lease.mark_sent()
    await governor.release(lease)
    assert (await governor.snapshot(now=tomorrow))["used"] == 1


# ── rate & concurrency ──────────────────────────────────────────────────────

async def test_minute_bucket_refuses_when_drained(governor):
    gov = Governor(config=make_config(rate_burst=3, rate_per_minute=6, daily_hard_limit=100),
                   redis=governor._redis)
    leases = [await gov.acquire(Priority.INTERACTIVE) for _ in range(3)]
    with pytest.raises(ZohoRateLimitedError) as excinfo:
        await gov.acquire(Priority.INTERACTIVE, max_wait=0.05)
    assert excinfo.value.data["reason"] == "rate"
    for lease in leases:
        await gov.release(lease, sent=False)
    await gov.reset_day()


async def test_lower_priorities_leave_a_reserve_for_higher_ones(governor):
    gov = Governor(
        config=make_config(rate_burst=10, rate_per_minute=1, daily_hard_limit=100,
                           concurrency_limit=9),
        redis=governor._redis,
    )
    # RECONCILE must leave 50 % of the bucket: only 5 of 10 tokens are usable.
    for _ in range(5):
        lease = await gov.acquire(Priority.RECONCILE, max_wait=0)
        await gov.release(lease, sent=True)
    with pytest.raises(ZohoRateLimitedError) as excinfo:
        await gov.acquire(Priority.RECONCILE, max_wait=0)
    assert excinfo.value.data["reason"] == "rate"

    # interactive traffic still gets in — that is what the reserve is for
    lease = await gov.acquire(Priority.INTERACTIVE, max_wait=0)
    await gov.release(lease, sent=True)
    await gov.reset_day()


async def test_concurrency_is_capped_org_wide(governor):
    held = [await governor.acquire(Priority.PUSH) for _ in range(governor.config.concurrency_limit)]
    with pytest.raises(ZohoRateLimitedError) as excinfo:
        await governor.acquire(Priority.PUSH, max_wait=0.05)
    assert excinfo.value.data["reason"] == "concurrency"

    await governor.release(held.pop(), sent=False)
    freed = await governor.acquire(Priority.PUSH, max_wait=0.5)   # a slot opened
    await governor.release(freed, sent=False)
    for lease in held:
        await governor.release(lease, sent=False)


async def test_expired_leases_do_not_block_forever(redis_available):
    gov = Governor(config=make_config(concurrency_limit=1, lease_ttl_seconds=0.2),
                   redis=redis_available)
    stale = await gov.acquire(Priority.PUSH)      # simulate a crashed worker
    await asyncio.sleep(0.35)
    lease = await gov.acquire(Priority.PUSH, max_wait=0.5)
    assert lease.id != stale.id
    await gov.release(lease, sent=False)
    await gov.reset_day()


# ── pacing ──────────────────────────────────────────────────────────────────

async def test_pacing_curve_defers_background_work(redis_available):
    gov = Governor(
        config=make_config(daily_hard_limit=1_000, pacing_curve=PacingCurve.LINEAR, carry_pct=0.0),
        redis=redis_available,
    )
    day = gov.current_day()
    early = day.start + timedelta(minutes=1)      # ~0 % of the day unlocked

    with pytest.raises(ZohoBudgetDeferred) as excinfo:
        await gov.acquire(Priority.INCREMENTAL, now=early)
    assert excinfo.value.reason == "pacing"

    # foreground traffic ignores the curve
    lease = await gov.acquire(Priority.PUSH, now=early)
    await gov.release(lease, sent=False)
    await gov.reset_day()


# ── degraded mode ───────────────────────────────────────────────────────────

class _BrokenRedis:
    """Every command raises, like a Redis outage."""

    def register_script(self, script):
        async def _call(keys=None, args=None):
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("redis is down")

        return _call


async def test_degraded_mode_allows_foreground_and_stops_background():
    gov = Governor(config=make_config(expected_processes=2, rate_per_minute=60), redis=_BrokenRedis())

    lease = await gov.acquire(Priority.INTERACTIVE)
    assert lease.degraded is True
    await gov.release(lease, sent=True)

    with pytest.raises(ZohoRateLimitedError):
        await gov.acquire(Priority.RECONCILE)


async def test_disabled_governor_is_a_no_op():
    gov = Governor(config=make_config(enabled=False), redis=_BrokenRedis())
    async with gov.slot(Priority.RECONCILE) as lease:
        lease.mark_sent()
    assert lease.settled is True
