"""Circuit breaker v2 — per endpoint group, owned single-probe recovery.

Why a rewrite of ``circuit_breaker.py`` (v1 stays until the transport lands):

| v1 defect | v2 |
|---|---|
| 429s recorded as failures — normal throttling opened the circuit | only ``TRANSIENT``/``AMBIGUOUS`` (5xx, timeouts, connection errors) count; the governor handles throttling |
| any in-flight success closed a HALF_OPEN circuit, not just the probe's | the probe holds a token; **only that token's outcome** closes or reopens |
| probe TTL (15 s) shorter than the HTTP read timeout (30 s) → two probes | probe TTL is derived from the read timeout with headroom |
| a probe ending in a business error left the circuit blind for 15 s | business errors release the probe immediately (they prove Zoho is answering) |
| fixed recovery window | recovery doubles per consecutive trip up to a cap |

Doctrine: the breaker protects Zoho *and us* from hammering a failing
endpoint group. It is a local, fail-open safety net — if Redis is unavailable
the call is allowed (the governor, not the breaker, is the fail-closed gate).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import StrEnum

import structlog
from redis.exceptions import RedisError

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.zoho.core.errors import (
    BREAKER_FAILURE_CATEGORIES,
    ErrorCategory,
    ZohoCircuitOpenError,
)

logger = structlog.get_logger("app.zoho.breaker")

_WINDOW_KEY = "zoho:cb:{group}:window"   # ZSET member "outcome:nonce" score = ts
_STATE_KEY = "zoho:cb:{group}:state"     # "open" with TTL = current recovery period
_META_KEY = "zoho:cb:{group}:meta"       # hash: trips, recovery_s, opened_at
_PROBE_KEY = "zoho:cb:{group}:probe"     # SET NX — the single half-open trial

_OK, _FAIL, _SLOW = "0", "1", "2"


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    window_seconds: int = 60
    min_calls: int = 10            # never judge on a handful of calls
    failure_ratio: float = 0.5
    slow_ratio: float = 0.5
    slow_seconds: float = 8.0
    recovery_seconds: int = 30     # first cool-down; doubles per consecutive trip
    recovery_max_seconds: int = 300
    probe_ttl_seconds: float = 45.0  # > HTTP read timeout, so one probe at a time

    @classmethod
    def from_settings(cls) -> "BreakerConfig":
        return cls(
            window_seconds=settings.ZOHO_CB_WINDOW_SECONDS,
            min_calls=settings.ZOHO_CB_MIN_CALLS,
            failure_ratio=settings.ZOHO_CB_FAILURE_RATE,
            slow_ratio=settings.ZOHO_CB_SLOW_RATE,
            slow_seconds=settings.ZOHO_CB_SLOW_SECONDS,
            recovery_seconds=settings.ZOHO_CB_RECOVERY_SECONDS,
            recovery_max_seconds=settings.ZOHO_CB_RECOVERY_MAX_SECONDS,
            probe_ttl_seconds=settings.ZOHO_TIMEOUT_SECONDS + 15.0,
        )


def endpoint_group(api: str, path: str) -> str:
    """Breaker key: the API plus the first path segment.

    ``books:/invoices/982000000567114`` → ``books:invoices``. Never per URL —
    the PHP engine keyed on ``md5(url)`` and every record had its own circuit,
    so ``minimum_requests`` was never reached and the breaker never tripped.
    """
    segment = path.strip("/").split("/", 1)[0] or "root"
    return f"{api}:{segment}"


@dataclass(slots=True)
class Admission:
    """Result of :meth:`ZohoCircuitBreaker.allow`."""

    group: str
    probe_id: str | None = None      # set when this caller is the single trial

    @property
    def is_probe(self) -> bool:
        return self.probe_id is not None


class ZohoCircuitBreaker:
    def __init__(self, config: BreakerConfig | None = None, redis=None) -> None:
        self._config = config or BreakerConfig.from_settings()
        self._redis = redis if redis is not None else redis_client

    @property
    def config(self) -> BreakerConfig:
        return self._config

    # ── state ───────────────────────────────────────────────────────────────

    async def state(self, group: str) -> BreakerState:
        try:
            if await self._redis.get(_STATE_KEY.format(group=group)):
                return BreakerState.OPEN
            trips = await self._redis.hget(_META_KEY.format(group=group), "trips")
            # The meta hash outlives the state key: its presence after the TTL
            # lapsed is what makes the group "recovering" rather than closed.
            return BreakerState.HALF_OPEN if trips else BreakerState.CLOSED
        except RedisError as exc:
            logger.warning("zoho.breaker.storage_error", group=group, error=str(exc))
            return BreakerState.CLOSED        # fail open

    # ── gate ────────────────────────────────────────────────────────────────

    async def allow(self, group: str) -> Admission:
        """Raise ``ZohoCircuitOpenError`` when the group is not callable."""
        state = await self.state(group)
        if state is BreakerState.CLOSED:
            return Admission(group)

        if state is BreakerState.OPEN:
            ttl = await self._ttl(_STATE_KEY.format(group=group))
            raise ZohoCircuitOpenError(
                f"Zoho '{group}' circuit is open; retry in ~{ttl}s",
                retry_after=float(ttl),
                data={"group": group, "state": str(state)},
            )

        # HALF_OPEN: exactly one caller gets the probe token.
        probe_id = uuid.uuid4().hex
        try:
            won = await self._redis.set(
                _PROBE_KEY.format(group=group), probe_id,
                nx=True, px=int(self._config.probe_ttl_seconds * 1000),
            )
        except RedisError:
            return Admission(group)           # fail open
        if not won:
            raise ZohoCircuitOpenError(
                f"Zoho '{group}' circuit is half-open; another worker is probing",
                retry_after=self._config.probe_ttl_seconds,
                data={"group": group, "state": str(state)},
            )
        logger.info("zoho.breaker.probe_started", group=group)
        return Admission(group, probe_id=probe_id)

    # ── outcomes ────────────────────────────────────────────────────────────

    async def record_success(self, admission: Admission, *, duration: float = 0.0) -> None:
        group = admission.group
        if admission.is_probe:
            if await self._owns_probe(group, admission.probe_id):
                await self._close(group, reason="probe_succeeded")
            return
        outcome = _SLOW if duration >= self._config.slow_seconds else _OK
        await self._record(group, outcome)

    async def record_failure(
        self, admission: Admission, *, category: ErrorCategory, duration: float = 0.0
    ) -> None:
        """Only infrastructure failures count; business errors are not outages."""
        group = admission.group
        counts = category in BREAKER_FAILURE_CATEGORIES

        if admission.is_probe:
            if not await self._owns_probe(group, admission.probe_id):
                return
            if counts:
                await self._open(group, reason=f"probe_failed:{category}")
            else:
                # Zoho answered (400/404/429) — it is up; end the trial cleanly.
                await self._close(group, reason=f"probe_business_error:{category}")
            return

        if counts:
            await self._record(group, _FAIL)

    # ── internals ───────────────────────────────────────────────────────────

    async def _owns_probe(self, group: str, probe_id: str | None) -> bool:
        if probe_id is None:
            return False
        try:
            current = await self._redis.get(_PROBE_KEY.format(group=group))
        except RedisError:
            return False
        return current == probe_id            # expired/stolen probes decide nothing

    async def _record(self, group: str, outcome: str) -> None:
        cfg = self._config
        now = time.time()
        window_key = _WINDOW_KEY.format(group=group)
        member = f"{outcome}:{uuid.uuid4().hex[:8]}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(window_key, "-inf", now - cfg.window_seconds)
                pipe.zadd(window_key, {member: now})
                pipe.zrange(window_key, 0, -1)
                pipe.expire(window_key, cfg.window_seconds * 2)
                results = await pipe.execute()
        except RedisError as exc:
            logger.warning("zoho.breaker.storage_error", group=group, error=str(exc))
            return

        window: list[str] = results[2]
        total = len(window)
        if total < cfg.min_calls:
            return
        failures = sum(1 for m in window if m.startswith(_FAIL))
        slow = sum(1 for m in window if m.startswith(_SLOW))
        if failures / total >= cfg.failure_ratio:
            await self._open(group, reason="failure_ratio", total=total, failures=failures)
        elif slow / total >= cfg.slow_ratio:
            await self._open(group, reason="slow_ratio", total=total, slow=slow)

    async def _open(self, group: str, *, reason: str, **fields) -> None:
        cfg = self._config
        meta_key = _META_KEY.format(group=group)
        try:
            trips = int(await self._redis.hincrby(meta_key, "trips", 1))
            recovery = min(cfg.recovery_seconds * (2 ** (trips - 1)), cfg.recovery_max_seconds)
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.set(_STATE_KEY.format(group=group), BreakerState.OPEN.value, ex=recovery)
                pipe.hset(meta_key, mapping={"recovery_s": recovery, "opened_at": time.time()})
                # Meta outlives the state key so the lapse reads as HALF_OPEN.
                pipe.expire(meta_key, recovery + cfg.window_seconds * 4)
                pipe.delete(_WINDOW_KEY.format(group=group), _PROBE_KEY.format(group=group))
                await pipe.execute()
        except RedisError as exc:
            logger.warning("zoho.breaker.storage_error", group=group, error=str(exc))
            return
        logger.error("zoho.breaker.opened", group=group, reason=reason, recovery_s=recovery,
                     trips=trips, **fields)

    async def _close(self, group: str, *, reason: str) -> None:
        try:
            await self._redis.delete(
                _STATE_KEY.format(group=group),
                _META_KEY.format(group=group),
                _WINDOW_KEY.format(group=group),
                _PROBE_KEY.format(group=group),
            )
        except RedisError as exc:
            logger.warning("zoho.breaker.storage_error", group=group, error=str(exc))
            return
        logger.info("zoho.breaker.closed", group=group, reason=reason)

    async def _ttl(self, key: str) -> int:
        try:
            return max(int(await self._redis.ttl(key)), 0)
        except RedisError:
            return 0

    # ── observability / operations ──────────────────────────────────────────

    async def snapshot(self, group: str) -> dict:
        state = await self.state(group)
        meta: dict[str, str] = {}
        window_size = 0
        try:
            meta = await self._redis.hgetall(_META_KEY.format(group=group)) or {}
            window_size = int(await self._redis.zcard(_WINDOW_KEY.format(group=group)))
        except RedisError:
            pass
        return {
            "group": group,
            "state": str(state),
            "state_code": {BreakerState.CLOSED: 0, BreakerState.HALF_OPEN: 1, BreakerState.OPEN: 2}[state],
            "trips": int(meta.get("trips", 0) or 0),
            "recovery_seconds": int(meta.get("recovery_s", 0) or 0),
            "window_calls": window_size,
            "retry_after": await self._ttl(_STATE_KEY.format(group=group)),
        }

    async def reset(self, group: str) -> None:
        """Operator action (audited by the caller): force a group closed."""
        await self._close(group, reason="operator_reset")


zoho_breaker = ZohoCircuitBreaker()

__all__ = [
    "Admission",
    "BreakerConfig",
    "BreakerState",
    "ZohoCircuitBreaker",
    "endpoint_group",
    "zoho_breaker",
]
