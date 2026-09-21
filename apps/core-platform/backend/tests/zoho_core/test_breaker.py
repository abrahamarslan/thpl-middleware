"""Circuit breaker v2 — the guarantees the v1 breaker did not provide."""

import asyncio
import uuid
from dataclasses import replace

import pytest

from app.modules.zoho.core.breaker import (
    BreakerConfig,
    BreakerState,
    ZohoCircuitBreaker,
    endpoint_group,
)
from app.modules.zoho.core.errors import ErrorCategory, ZohoCircuitOpenError


def make_breaker(redis, **overrides) -> ZohoCircuitBreaker:
    config = replace(
        BreakerConfig(
            window_seconds=60, min_calls=4, failure_ratio=0.5, slow_ratio=0.5,
            slow_seconds=1.0, recovery_seconds=1, recovery_max_seconds=4,
            probe_ttl_seconds=2.0,
        ),
        **overrides,
    )
    return ZohoCircuitBreaker(config=config, redis=redis)


@pytest.fixture
async def breaker(redis_available):
    yield make_breaker(redis_available)


@pytest.fixture
def group() -> str:
    return f"books:test{uuid.uuid4().hex[:8]}"


async def fail(breaker: ZohoCircuitBreaker, group: str, times: int,
               category: ErrorCategory = ErrorCategory.TRANSIENT) -> None:
    for _ in range(times):
        admission = await breaker.allow(group)
        await breaker.record_failure(admission, category=category)


def test_endpoint_group_is_api_plus_first_segment():
    assert endpoint_group("books", "/invoices/982000000567114") == "books:invoices"
    assert endpoint_group("inventory", "/items/batches") == "inventory:items"
    assert endpoint_group("books", "/") == "books:root"


async def test_closed_circuit_allows_calls(breaker, group):
    admission = await breaker.allow(group)
    assert admission.is_probe is False
    await breaker.record_success(admission, duration=0.1)
    assert await breaker.state(group) is BreakerState.CLOSED


async def test_infrastructure_failures_open_the_circuit(breaker, group):
    await fail(breaker, group, 4)
    assert await breaker.state(group) is BreakerState.OPEN
    with pytest.raises(ZohoCircuitOpenError) as excinfo:
        await breaker.allow(group)
    assert excinfo.value.data["group"] == group


@pytest.mark.parametrize(
    "category",
    [ErrorCategory.RATE_LIMITED, ErrorCategory.QUOTA_EXHAUSTED, ErrorCategory.VALIDATION,
     ErrorCategory.NOT_FOUND, ErrorCategory.FORBIDDEN],
)
async def test_business_and_throttle_failures_never_open_the_circuit(breaker, group, category):
    await fail(breaker, group, 20, category=category)
    assert await breaker.state(group) is BreakerState.CLOSED


async def test_slow_calls_open_the_circuit(breaker, group):
    for _ in range(4):
        admission = await breaker.allow(group)
        await breaker.record_success(admission, duration=5.0)   # slow_seconds = 1.0
    assert await breaker.state(group) is BreakerState.OPEN


async def test_min_calls_prevents_tripping_on_noise(breaker, group):
    await fail(breaker, group, 3)          # min_calls = 4
    assert await breaker.state(group) is BreakerState.CLOSED


async def test_only_one_probe_runs_in_half_open(breaker, group):
    await fail(breaker, group, 4)
    await asyncio.sleep(1.2)               # recovery_seconds = 1
    assert await breaker.state(group) is BreakerState.HALF_OPEN

    probe = await breaker.allow(group)
    assert probe.is_probe is True
    with pytest.raises(ZohoCircuitOpenError):
        await breaker.allow(group)         # everyone else keeps fast-failing


async def test_only_the_probe_can_close_the_circuit(breaker, group):
    await fail(breaker, group, 4)
    await asyncio.sleep(1.2)
    probe = await breaker.allow(group)

    # A late in-flight success from before the trip must NOT close it (v1 bug).
    stale = type(probe)(group=group)       # non-probe admission
    await breaker.record_success(stale, duration=0.1)
    assert await breaker.state(group) is BreakerState.HALF_OPEN

    await breaker.record_success(probe, duration=0.1)
    assert await breaker.state(group) is BreakerState.CLOSED


async def test_probe_failure_reopens_with_a_longer_recovery(breaker, group):
    await fail(breaker, group, 4)
    first = (await breaker.snapshot(group))["recovery_seconds"]
    await asyncio.sleep(1.2)

    probe = await breaker.allow(group)
    await breaker.record_failure(probe, category=ErrorCategory.TRANSIENT)

    snapshot = await breaker.snapshot(group)
    assert snapshot["state"] == BreakerState.OPEN
    assert snapshot["recovery_seconds"] > first          # doubling
    assert snapshot["trips"] == 2


async def test_probe_business_error_closes_the_circuit(breaker, group):
    """A 404/400 during the trial proves Zoho is answering — stop blocking."""
    await fail(breaker, group, 4)
    await asyncio.sleep(1.2)
    probe = await breaker.allow(group)
    await breaker.record_failure(probe, category=ErrorCategory.VALIDATION)
    assert await breaker.state(group) is BreakerState.CLOSED


async def test_recovery_backoff_doubles_and_is_capped(breaker, group):
    # recovery_seconds=1, recovery_max_seconds=4 → 1, 2, 4, 4, 4 …
    seen = []
    for _ in range(5):
        await breaker._open(group, reason="test")
        seen.append((await breaker.snapshot(group))["recovery_seconds"])
    assert seen == [1, 2, 4, 4, 4]
    assert max(seen) <= breaker.config.recovery_max_seconds


async def test_reset_closes_the_circuit(breaker, group):
    await fail(breaker, group, 4)
    await breaker.reset(group)
    assert await breaker.state(group) is BreakerState.CLOSED
    assert (await breaker.snapshot(group))["trips"] == 0


class _BrokenRedis:
    """Redis outage: the breaker must fail OPEN (allow traffic)."""

    async def get(self, *a, **k):
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("down")

    hget = hgetall = zcard = ttl = set = delete = get


async def test_breaker_fails_open_when_redis_is_down(group):
    breaker = ZohoCircuitBreaker(config=BreakerConfig(), redis=_BrokenRedis())
    admission = await breaker.allow(group)          # no exception
    assert admission.is_probe is False
    assert await breaker.state(group) is BreakerState.CLOSED
