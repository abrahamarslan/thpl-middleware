"""Time-based sliding-window circuit breaker (integration: real Redis)."""

import asyncio
import uuid

import pytest

from app.core.conf import settings
from app.modules.zoho.core.circuit_breaker import CircuitState, ZohoCircuitBreaker
from app.modules.zoho.core.exceptions import ZohoCircuitOpenError


@pytest.fixture
def breaker(redis_available, monkeypatch):
    # Small thresholds so tests run in milliseconds/seconds
    monkeypatch.setattr(settings, "ZOHO_CB_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "ZOHO_CB_MIN_CALLS", 4)
    monkeypatch.setattr(settings, "ZOHO_CB_FAILURE_RATE", 0.5)
    monkeypatch.setattr(settings, "ZOHO_CB_SLOW_RATE", 0.5)
    monkeypatch.setattr(settings, "ZOHO_CB_SLOW_SECONDS", 5.0)
    monkeypatch.setattr(settings, "ZOHO_CB_RECOVERY_SECONDS", 1)
    return ZohoCircuitBreaker()


def _key() -> str:
    return f"testcb-{uuid.uuid4().hex[:8]}"


async def test_stays_closed_below_min_calls(breaker):
    key = _key()
    for _ in range(3):  # 3 failures < MIN_CALLS=4 -> no evaluation yet
        await breaker.record_failure(key)
    assert await breaker.get_state(key) is CircuitState.CLOSED
    await breaker.check(key)  # does not raise


async def test_failure_rate_trips_the_circuit(breaker):
    key = _key()
    await breaker.record_success(key, duration=0.1)
    for _ in range(3):  # 3 fail / 4 total = 75% >= 50%
        await breaker.record_failure(key)
    assert await breaker.get_state(key) is CircuitState.OPEN
    with pytest.raises(ZohoCircuitOpenError):
        await breaker.check(key)


async def test_slow_call_rate_trips_the_circuit(breaker):
    key = _key()
    await breaker.record_success(key, duration=0.1)
    for _ in range(3):  # slow calls, not failures
        await breaker.record_success(key, duration=9.0)
    assert await breaker.get_state(key) is CircuitState.OPEN


async def test_successes_do_not_trip(breaker):
    key = _key()
    for _ in range(10):
        await breaker.record_success(key, duration=0.05)
    assert await breaker.get_state(key) is CircuitState.CLOSED


async def test_half_open_single_probe_then_close(breaker):
    key = _key()
    for _ in range(4):
        await breaker.record_failure(key)
    assert await breaker.get_state(key) is CircuitState.OPEN

    await asyncio.sleep(1.2)  # recovery TTL lapses -> HALF_OPEN
    assert await breaker.get_state(key) is CircuitState.HALF_OPEN

    await breaker.check(key)  # first caller wins the probe lock
    with pytest.raises(ZohoCircuitOpenError):
        await breaker.check(key)  # everyone else keeps fast-failing

    await breaker.record_success(key, duration=0.1)  # probe succeeded
    assert await breaker.get_state(key) is CircuitState.CLOSED
    await breaker.check(key)


async def test_half_open_probe_failure_reopens(breaker):
    key = _key()
    for _ in range(4):
        await breaker.record_failure(key)
    await asyncio.sleep(1.2)
    assert await breaker.get_state(key) is CircuitState.HALF_OPEN

    await breaker.check(key)
    await breaker.record_failure(key)  # probe failed
    assert await breaker.get_state(key) is CircuitState.OPEN
