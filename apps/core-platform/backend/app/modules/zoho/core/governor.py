"""The Zoho governor — one gate for the daily quota, the per-minute rate and
org-wide concurrency.

Replaces the three separate gates of the first design (rate limiter, daily
quota, concurrency semaphore) with a single atomic admission decision, because
they are one decision: *may this call go out right now?*

Why it exists (docs/zoho-sync-platform-architecture-delta-v3.1.md §3):
  - Zoho's **daily** limit binds long before the per-minute one. Ours is a
    contracted 45,000/day; a runaway sweep can burn it in an hour.
  - Exceeding 100 req/min returns code 44 and Zoho **blocks the whole
    organization**, including people working in the Zoho web UI. The minute
    bucket therefore degrades *closed*, never open.
  - Exceeding the concurrent-call cap returns code 1070.

Guarantees:
  - Nothing reaches ``zohoapis.*`` without a lease from this object.
  - Spend is reserved before the call and committed only if it was sent, so
    concurrent workers cannot overshoot the ceiling.
  - When the ceiling is reached the engine *stops* (``QUOTA_EXHAUSTED``);
    lanes, sync requests and outbox commands persist where they stopped and
    the planner resumes them after the quota day rolls over.
  - Redis loss degrades to a conservative per-process budget rather than an
    unlimited one.

Priorities and what they may still do as the day fills up are in
``GovernorState``/``Priority`` below; the thresholds are configuration.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, model_validator
from redis.exceptions import RedisError

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.zoho.core.errors import (
    ZohoBudgetDeferred,
    ZohoQuotaExhaustedError,
    ZohoRateLimitedError,
)
from app.modules.zoho.core.pacing import PacingCurve, QuotaDay, allowance, quota_day

logger = structlog.get_logger("app.zoho.governor")

_LUA_DIR = Path(__file__).parent / "lua"


class Priority(IntEnum):
    """Who is calling. The rank is what the Lua script compares against state."""

    INTERACTIVE = 0   # a user is waiting (API request, operator action, critical push)
    PUSH = 1          # outbox dispatcher
    REFRESH = 2       # webhook/write-back/record-error driven single or bulk refresh
    INCREMENTAL = 3   # scheduled change feeds and window scans
    RECONCILE = 4     # full scans, backfills, reports

    @property
    def is_background(self) -> bool:
        """Background priorities are subject to the pacing curve."""
        return self >= Priority.INCREMENTAL

    @property
    def max_wait_seconds(self) -> float:
        """How long this class may block waiting for rate/concurrency slots."""
        return {
            Priority.INTERACTIVE: 2.0,
            Priority.PUSH: 10.0,
            Priority.REFRESH: 5.0,
            Priority.INCREMENTAL: 5.0,
            Priority.RECONCILE: 0.0,
        }[self]

    @property
    def rate_reserve_fraction(self) -> float:
        """Fraction of the minute bucket this class must leave to higher ones."""
        return {
            Priority.INTERACTIVE: 0.0,
            Priority.PUSH: 0.10,
            Priority.REFRESH: 0.20,
            Priority.INCREMENTAL: 0.35,
            Priority.RECONCILE: 0.50,
        }[self]


class GovernorState(StrEnum):
    OPEN = "open"                    # everything runs
    CONSERVE = "conserve"            # reconcile/backfill/reports stop
    ESSENTIAL = "essential"          # + change feeds and sync requests stop
    RESERVED_ONLY = "reserved_only"  # only interactive/critical, from the reserve
    EXHAUSTED = "exhausted"          # nothing — resumes at the next quota day

    @property
    def max_rank(self) -> int:
        return {
            GovernorState.OPEN: 4,
            GovernorState.CONSERVE: 3,
            GovernorState.ESSENTIAL: 2,
            GovernorState.RESERVED_ONLY: 0,
            GovernorState.EXHAUSTED: -1,
        }[self]


class GovernorConfig(BaseModel):
    """Effective governor configuration (facade over ``app.core.conf``).

    Runtime overrides (system settings) will be merged in by the config
    resolver; the contract limit is the one bound no override may exceed.
    """

    enabled: bool = True
    pool: str = "zoho"
    org_id: str = ""

    contract_daily_limit: int = Field(default=45_000, ge=1)
    daily_hard_limit: int = Field(default=45_000, ge=1)
    soft_pct: float = Field(default=0.80, ge=0.0, le=1.0)
    essential_pct: float = Field(default=0.93, ge=0.0, le=1.0)
    hard_pct: float = Field(default=0.978, ge=0.0, le=1.0)
    reserve_calls: int = Field(default=1_000, ge=0)

    rate_per_minute: int = Field(default=80, ge=1, le=90)     # Zoho: 100 — keep headroom
    rate_burst: int = Field(default=10, ge=1, le=60)
    concurrency_limit: int = Field(default=6, ge=1, le=9)     # Zoho: ~10 (soft)

    quota_day_timezone: str = "Asia/Kolkata"
    quota_day_start: str = "00:00"

    pacing_curve: PacingCurve = PacingCurve.BUSINESS
    business_hours: str = "07:00-21:00"
    business_share: float = Field(default=0.7, ge=0.0, le=1.0)
    carry_pct: float = Field(default=0.05, ge=0.0, le=1.0)

    lease_ttl_seconds: float = Field(default=40.0, gt=0)
    expected_processes: int = Field(default=8, ge=1)

    @model_validator(mode="after")
    def _check_bounds(self) -> "GovernorConfig":
        if self.daily_hard_limit > self.contract_daily_limit:
            raise ValueError("daily_hard_limit may never exceed ZOHO_CONTRACT_DAILY_LIMIT")
        if not (self.soft_pct < self.essential_pct < self.hard_pct):
            raise ValueError("thresholds must increase: soft < essential < hard")
        return self

    # ── derived absolute thresholds ─────────────────────────────────────────
    @property
    def soft_threshold(self) -> int:
        return int(self.daily_hard_limit * self.soft_pct)

    @property
    def essential_threshold(self) -> int:
        return int(self.daily_hard_limit * self.essential_pct)

    @property
    def hard_threshold(self) -> int:
        return int(self.daily_hard_limit * self.hard_pct)

    def state_for(self, committed: int) -> GovernorState:
        if committed >= self.daily_hard_limit:
            return GovernorState.EXHAUSTED
        if committed >= self.hard_threshold:
            return GovernorState.RESERVED_ONLY
        if committed >= self.essential_threshold:
            return GovernorState.ESSENTIAL
        if committed >= self.soft_threshold:
            return GovernorState.CONSERVE
        return GovernorState.OPEN


def config_from_settings() -> GovernorConfig:
    """Layer 1 (environment) → typed governor config."""
    return GovernorConfig(
        enabled=settings.ZOHO_GOVERNOR_ENABLED,
        org_id=settings.ZOHO_ORGANIZATION_ID,
        contract_daily_limit=settings.ZOHO_CONTRACT_DAILY_LIMIT,
        daily_hard_limit=settings.ZOHO_DAILY_HARD_LIMIT,
        soft_pct=settings.ZOHO_QUOTA_SOFT_PCT,
        essential_pct=settings.ZOHO_QUOTA_ESSENTIAL_PCT,
        hard_pct=settings.ZOHO_QUOTA_HARD_PCT,
        reserve_calls=settings.ZOHO_QUOTA_RESERVE_CALLS,
        rate_per_minute=settings.ZOHO_RATE_LIMIT_PER_MINUTE,
        rate_burst=settings.ZOHO_RATE_BURST,
        concurrency_limit=settings.ZOHO_MAX_CONCURRENT_REQUESTS,
        quota_day_timezone=settings.ZOHO_QUOTA_DAY_TIMEZONE,
        quota_day_start=settings.ZOHO_QUOTA_DAY_START,
        pacing_curve=PacingCurve(settings.ZOHO_PACING_CURVE),
        business_hours=settings.ZOHO_BUSINESS_HOURS,
        business_share=settings.ZOHO_PACING_BUSINESS_SHARE,
        carry_pct=settings.ZOHO_PACING_CARRY_PCT,
        lease_ttl_seconds=settings.ZOHO_GOVERNOR_LEASE_TTL_SECONDS,
        expected_processes=settings.ZOHO_GOVERNOR_EXPECTED_PROCESSES,
    )


@dataclass(slots=True)
class Lease:
    """An admission. Settled exactly once by :meth:`Governor.release`."""

    id: str
    priority: Priority
    cost: int
    background: bool
    day_key: str
    state: GovernorState
    module: str | None = None
    purpose: str | None = None
    acquired_at: float = field(default_factory=time.monotonic)
    degraded: bool = False          # granted by the local fallback, not Redis
    sent: bool = False              # set by the transport once bytes went out
    settled: bool = False

    def mark_sent(self) -> None:
        self.sent = True

    @property
    def held_seconds(self) -> float:
        return time.monotonic() - self.acquired_at


class _LocalFallback:
    """Per-process budget used only while Redis is unreachable.

    Deliberately conservative: the whole-fleet limits divided by the expected
    number of processes, and background work is refused outright. Losing the
    shared counter must never let the fleet exceed Zoho's per-minute limit
    (code 44 blocks the organization).

    Primitives are created per running event loop — Celery tasks run their own
    loop per process, and an ``asyncio`` primitive bound to a dead loop raises.
    """

    def __init__(self, config: GovernorConfig) -> None:
        self._config = config
        self._state: dict[int, dict[str, Any]] = {}

    def _loop_state(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        key = id(loop)
        state = self._state.get(key)
        if state is None:
            share = max(self._config.rate_per_minute // self._config.expected_processes, 1)
            state = {
                "semaphore": asyncio.Semaphore(
                    max(self._config.concurrency_limit // self._config.expected_processes, 1)
                ),
                "tokens": float(share),
                "capacity": float(share),
                "refill_per_s": share / 60.0,
                "ts": time.monotonic(),
            }
            self._state[key] = state
        return state

    async def acquire(self, priority: Priority, cost: int) -> bool:
        if priority.is_background:
            return False                      # no background work without the shared counter
        state = self._loop_state()
        now = time.monotonic()
        state["tokens"] = min(
            state["capacity"], state["tokens"] + (now - state["ts"]) * state["refill_per_s"]
        )
        state["ts"] = now
        if state["tokens"] < cost:
            return False
        await state["semaphore"].acquire()
        state["tokens"] -= cost
        return True

    def release(self) -> None:
        try:
            self._loop_state()["semaphore"].release()
        except (RuntimeError, ValueError):     # loop gone / not acquired here
            pass


class Governor:
    """The single admission gate for every Zoho call."""

    def __init__(self, config: GovernorConfig | None = None, redis=None) -> None:
        self._config = config or config_from_settings()
        self._redis = redis if redis is not None else redis_client
        self._fallback = _LocalFallback(self._config)
        self._acquire_script = None
        self._release_script = None
        self._degraded_since: float | None = None

    # ── configuration ───────────────────────────────────────────────────────

    @property
    def config(self) -> GovernorConfig:
        return self._config

    def reconfigure(self, config: GovernorConfig) -> None:
        """Hot-swap configuration (runtime overrides, tests)."""
        self._config = config
        self._fallback = _LocalFallback(config)

    # ── keys ────────────────────────────────────────────────────────────────

    def current_day(self, now: datetime | None = None) -> QuotaDay:
        return quota_day(
            now or datetime.now(UTC),
            timezone=self._config.quota_day_timezone,
            day_start=self._config.quota_day_start,
        )

    def _day_key(self, day: QuotaDay) -> str:
        return f"zoho:gov:{self._config.pool}:day:{day.key}"

    def _rate_key(self) -> str:
        return f"zoho:gov:{self._config.org_id or 'org'}:minute"

    def _inflight_key(self) -> str:
        return f"zoho:gov:{self._config.org_id or 'org'}:inflight"

    def _scripts(self):
        if self._acquire_script is None:
            self._acquire_script = self._redis.register_script(
                (_LUA_DIR / "governor_acquire.lua").read_text(encoding="utf-8")
            )
            self._release_script = self._redis.register_script(
                (_LUA_DIR / "governor_release.lua").read_text(encoding="utf-8")
            )
        return self._acquire_script, self._release_script

    # ── admission ───────────────────────────────────────────────────────────

    async def acquire(
        self,
        priority: Priority,
        *,
        cost: int = 1,
        module: str | None = None,
        purpose: str | None = None,
        max_wait: float | None = None,
        now: datetime | None = None,
    ) -> Lease:
        """Reserve budget for one call, waiting for rate/concurrency if allowed.

        Raises:
            ZohoQuotaExhaustedError: the daily ceiling for this priority is reached.
            ZohoBudgetDeferred: this priority is paused by the governor state or
                the pacing curve (background work: yield and come back later).
            ZohoRateLimitedError: rate/concurrency slots did not free up within
                the priority's wait budget.
        """
        if not self._config.enabled:
            day = self.current_day(now)
            return Lease(
                id=uuid.uuid4().hex, priority=priority, cost=cost,
                background=priority.is_background, day_key=day.key,
                state=GovernorState.OPEN, module=module, purpose=purpose, degraded=True,
            )

        deadline = time.monotonic() + (priority.max_wait_seconds if max_wait is None else max_wait)
        day = self.current_day(now)
        attempt = 0

        while True:
            attempt += 1
            try:
                result = await self._try_acquire(priority, cost, day, module, purpose, now)
            except RedisError as exc:
                return await self._acquire_degraded(priority, cost, day, module, purpose, exc)

            if isinstance(result, Lease):
                return result

            reason, retry_after_ms, state = result
            if reason in ("state", "quota"):
                self._raise_for_state(reason, state, day, priority, module)
            if reason == "pacing":
                raise ZohoBudgetDeferred(
                    f"Zoho background allowance for {day.key} is spent; {module or 'engine'} deferred",
                    reason="pacing",
                    retry_at=day.resets_at_iso(),
                    module=module,
                    retry_after=retry_after_ms / 1000,
                )

            wait = min(retry_after_ms / 1000, 5.0)
            if time.monotonic() + wait > deadline:
                raise ZohoRateLimitedError(
                    f"Zoho {reason} budget unavailable for {priority.name.lower()} traffic",
                    retry_after=wait,
                    module=module,
                    data={"reason": reason, "state": str(state), "attempts": attempt},
                )
            await asyncio.sleep(wait)

    async def _try_acquire(
        self,
        priority: Priority,
        cost: int,
        day: QuotaDay,
        module: str | None,
        purpose: str | None,
        now: datetime | None,
    ) -> Lease | tuple[str, int, GovernorState]:
        cfg = self._config
        acquire_script, _ = self._scripts()
        lease_id = uuid.uuid4().hex
        background = priority.is_background
        bg_allowance = allowance(
            now or datetime.now(UTC),
            day,
            ceiling=cfg.hard_threshold,
            curve=cfg.pacing_curve,
            business_hours=cfg.business_hours,
            business_share=cfg.business_share,
            carry_pct=cfg.carry_pct,
        )
        raw = await acquire_script(
            keys=[self._day_key(day), self._rate_key(), self._inflight_key()],
            args=[
                int(time.time() * 1000),                       # 1 now_ms
                int(priority),                                 # 2 rank
                cost,                                          # 3 cost
                lease_id,                                      # 4 lease id
                int(cfg.lease_ttl_seconds * 1000),             # 5 lease ttl
                cfg.soft_threshold,                            # 6
                cfg.essential_threshold,                       # 7
                cfg.hard_threshold,                            # 8
                cfg.reserve_calls,                             # 9
                cfg.rate_burst,                                # 10 capacity
                cfg.rate_per_minute / 60000.0,                 # 11 refill per ms
                cfg.concurrency_limit,                         # 12
                cfg.daily_hard_limit,                          # 13
                int(cfg.lease_ttl_seconds * 1000),             # 14 (reserved)
                1 if background else 0,                        # 15
                bg_allowance,                                  # 16
                day.ttl_seconds,                               # 17
                int(cfg.rate_burst * priority.rate_reserve_fraction),  # 18
            ],
        )

        ok = int(raw[0])
        state = GovernorState(str(raw[1] if ok else raw[3]))
        if ok:
            self._degraded_since = None
            return Lease(
                id=lease_id, priority=priority, cost=cost, background=background,
                day_key=day.key, state=state, module=module, purpose=purpose,
            )
        return str(raw[1]), int(raw[2]), state

    def _raise_for_state(
        self, reason: str, state: GovernorState, day: QuotaDay, priority: Priority, module: str | None
    ) -> None:
        if state is GovernorState.EXHAUSTED or reason == "quota":
            raise ZohoQuotaExhaustedError(
                f"Zoho daily call ceiling reached for pool '{self._config.pool}' ({day.key})",
                resets_at=day.resets_at_iso(),
                module=module,
                data={"state": str(state), "priority": priority.name.lower()},
            )
        raise ZohoBudgetDeferred(
            f"governor is in '{state}' — {priority.name.lower()} traffic is paused",
            reason=f"state:{state}",
            retry_at=day.resets_at_iso(),
            module=module,
        )

    async def _acquire_degraded(
        self,
        priority: Priority,
        cost: int,
        day: QuotaDay,
        module: str | None,
        purpose: str | None,
        exc: Exception,
    ) -> Lease:
        """Redis is unreachable: fall back to a conservative per-process budget."""
        now = time.monotonic()
        if self._degraded_since is None or now - self._degraded_since > 60:
            self._degraded_since = now
            logger.error("zoho.governor.degraded", error=str(exc), module=module)
        granted = await self._fallback.acquire(priority, cost)
        if not granted:
            raise ZohoRateLimitedError(
                "Zoho governor is degraded (Redis unavailable); background traffic is paused",
                retry_after=30.0,
                module=module,
                data={"degraded": True, "priority": priority.name.lower()},
            )
        return Lease(
            id=uuid.uuid4().hex, priority=priority, cost=cost,
            background=priority.is_background, day_key=day.key,
            state=GovernorState.ESSENTIAL, module=module, purpose=purpose, degraded=True,
        )

    # ── settlement ──────────────────────────────────────────────────────────

    async def release(self, lease: Lease, *, sent: bool | None = None) -> GovernorState | None:
        """Settle a lease: commit the spend if the request was sent, else refund."""
        if lease.settled:
            return None
        lease.settled = True
        was_sent = lease.sent if sent is None else sent

        if lease.degraded:
            self._fallback.release()
            return None
        if not self._config.enabled:
            return None

        cfg = self._config
        try:
            _, release_script = self._scripts()
            raw = await release_script(
                keys=[f"zoho:gov:{cfg.pool}:day:{lease.day_key}", self._inflight_key()],
                args=[
                    lease.id, lease.cost, 1 if was_sent else 0,
                    1 if lease.background else 0, int(lease.priority),
                    86_400 + 7_200, cfg.soft_threshold, cfg.essential_threshold,
                    cfg.hard_threshold, cfg.daily_hard_limit,
                ],
            )
        except RedisError as exc:
            logger.error("zoho.governor.release_failed", error=str(exc), lease=lease.id)
            return None

        state = GovernorState(str(raw[2]))
        if state is not lease.state:
            logger.info(
                "zoho.governor.state_changed",
                **{"from": str(lease.state), "to": str(state), "used": int(raw[0]), "pool": cfg.pool},
            )
        return state

    @asynccontextmanager
    async def slot(self, priority: Priority, **kwargs: Any):
        """``async with governor.slot(Priority.PUSH) as lease: … lease.mark_sent()``"""
        lease = await self.acquire(priority, **kwargs)
        try:
            yield lease
        finally:
            await self.release(lease)

    # ── operations ──────────────────────────────────────────────────────────

    async def mark_quota_exhausted(self, *, reason: str = "zoho_code_45", now: datetime | None = None) -> None:
        """Zoho says the daily limit is gone — believe Zoho, not our counter."""
        day = self.current_day(now)
        try:
            await self._redis.hset(self._day_key(day), mapping={"exhausted": 1, "state": "exhausted"})
            await self._redis.expire(self._day_key(day), day.ttl_seconds)
        except RedisError as exc:
            logger.error("zoho.governor.mark_exhausted_failed", error=str(exc))
        logger.critical(
            "zoho.governor.quota_exhausted", pool=self._config.pool, day=day.key,
            reason=reason, resets_at=day.resets_at_iso(),
        )

    async def snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        """Current counters — for /metrics, the admin API and the planner."""
        cfg = self._config
        day = self.current_day(now)
        used = reserved = used_bg = 0
        exhausted = False
        inflight = 0
        tokens: float | None = None
        healthy = True
        try:
            values = await self._redis.hmget(
                self._day_key(day), "used", "reserved", "used_bg", "exhausted"
            )
            used, reserved, used_bg = (int(v or 0) for v in values[:3])
            exhausted = bool(int(values[3] or 0))
            inflight = int(await self._redis.zcount(self._inflight_key(), int(time.time() * 1000), "+inf"))
            bucket = await self._redis.hget(self._rate_key(), "tokens")
            tokens = float(bucket) if bucket is not None else None
        except (RedisError, ValueError, TypeError):
            healthy = False

        committed = used + reserved
        state = GovernorState.EXHAUSTED if exhausted else cfg.state_for(committed)
        return {
            "pool": cfg.pool,
            "enabled": cfg.enabled,
            "healthy": healthy,
            "day": day.key,
            "resets_at": day.resets_at_iso(),
            "state": str(state),
            "used": used,
            "reserved": reserved,
            "used_background": used_bg,
            "remaining": max(cfg.daily_hard_limit - committed, 0),
            "daily_hard_limit": cfg.daily_hard_limit,
            "thresholds": {
                "soft": cfg.soft_threshold,
                "essential": cfg.essential_threshold,
                "hard": cfg.hard_threshold,
                "reserve_calls": cfg.reserve_calls,
            },
            "background_allowance": allowance(
                now or datetime.now(UTC), day, ceiling=cfg.hard_threshold,
                curve=cfg.pacing_curve, business_hours=cfg.business_hours,
                business_share=cfg.business_share, carry_pct=cfg.carry_pct,
            ),
            "rate_tokens": tokens,
            "rate_per_minute": cfg.rate_per_minute,
            "inflight": inflight,
            "concurrency_limit": cfg.concurrency_limit,
        }

    async def reseed(
        self, *, used: int, used_background: int, exhausted: bool, now: datetime | None = None
    ) -> bool:
        """Raise today's counters to at least the durable values (never lower).

        Postgres (``zoho_quota_days``) holds the greatest count the planner
        ever saw; Redis is the live counter. If Redis restarted or evicted the
        day hash, the counters read low and the governor would hand the day's
        quota out a second time — Zoho's own counter did not reset. Atomic in
        one script, so calls admitted concurrently are never overwritten.
        Returns True when anything was raised.
        """
        day = self.current_day(now)
        try:
            raised = await self._redis.eval(
                _RESEED_LUA, 1, self._day_key(day),
                int(used), int(used_background), 1 if exhausted else 0, day.ttl_seconds,
            )
        except RedisError as exc:
            logger.warning("zoho.governor.reseed_failed", error=str(exc))
            return False
        if int(raised or 0):
            logger.warning(
                "zoho.governor.reseeded", pool=self._config.pool, day=day.key,
                used=used, used_background=used_background, exhausted=exhausted,
            )
            return True
        return False

    async def reset_day(self, now: datetime | None = None) -> None:
        """Test/operator helper: clear today's counters (audited by the caller)."""
        day = self.current_day(now)
        await self._redis.delete(self._day_key(day), self._rate_key(), self._inflight_key())


#: KEYS[1] day hash · ARGV used, used_bg, exhausted(0/1), ttl — raise-only.
_RESEED_LUA = """
local raised = 0
local used = tonumber(redis.call('HGET', KEYS[1], 'used') or '0')
if tonumber(ARGV[1]) > used then redis.call('HSET', KEYS[1], 'used', ARGV[1]); raised = 1 end
local used_bg = tonumber(redis.call('HGET', KEYS[1], 'used_bg') or '0')
if tonumber(ARGV[2]) > used_bg then redis.call('HSET', KEYS[1], 'used_bg', ARGV[2]); raised = 1 end
if ARGV[3] == '1' and tonumber(redis.call('HGET', KEYS[1], 'exhausted') or '0') ~= 1 then
  redis.call('HSET', KEYS[1], 'exhausted', 1); raised = 1
end
if raised == 1 and redis.call('TTL', KEYS[1]) < 0 then redis.call('EXPIRE', KEYS[1], ARGV[4]) end
return raised
"""

#: Process-wide instance; import this, never construct your own.
zoho_governor = Governor()


__all__ = [
    "Governor",
    "GovernorConfig",
    "GovernorState",
    "Lease",
    "Priority",
    "config_from_settings",
    "zoho_governor",
]
