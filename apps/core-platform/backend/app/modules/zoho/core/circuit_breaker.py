"""Redis-backed circuit breaker — time-based sliding window (ZSET).

Here every call outcome is a ZSET member scored by its timestamp, and ``ZREMRANGEBYSCORE`` purges
anything older than the window on every write, so the breaker's math is
strictly "the last N seconds", independent of traffic volume.

Trip conditions (evaluated only once the window holds >= MIN_CALLS):
  - failure rate  >= ZOHO_CB_FAILURE_RATE   (infra failures: 5xx/429/network)
  - slow-call rate >= ZOHO_CB_SLOW_RATE     (calls slower than SLOW_SECONDS)

States (shared by every API + Celery worker via Redis, per endpoint group):
  CLOSED     normal; outcomes recorded and evaluated
  OPEN       every call short-circuits for ZOHO_CB_RECOVERY_SECONDS
  HALF_OPEN  after the open TTL lapses ONE worker wins the probe lock and
             sends a trial call (no thundering herd); success closes the
             circuit, failure re-opens it

Interface is unchanged for callers (client.py): check / record_success /
record_failure — record_success now accepts the call duration so slow-call
detection works.
"""

import time
import uuid
from enum import Enum

import structlog

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.zoho.core.exceptions import ZohoCircuitOpenError

logger = structlog.get_logger("app.zoho.circuit")

_STATE_KEY = "zoho:cb:{key}:state"     # "open" with TTL = recovery period
_OPENED_KEY = "zoho:cb:{key}:opened"   # marker outliving state -> HALF_OPEN
_WINDOW_KEY = "zoho:cb:{key}:window"   # ZSET member "ts:outcome:nonce" score ts
_PROBE_KEY = "zoho:cb:{key}:probe"     # NX lock for the single half-open trial

_OUTCOME_OK, _OUTCOME_FAIL, _OUTCOME_SLOW = "0", "1", "2"
_PROBE_TTL = 15  # seconds a probe may run before another worker may try


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ZohoCircuitBreaker:
    # ── State inspection ─────────────────────────────────────────────────────

    async def get_state(self, key: str) -> CircuitState:
        if await redis_client.get(_STATE_KEY.format(key=key)):
            return CircuitState.OPEN
        # State TTL lapsed but the opened marker remains -> recovery probing.
        if await redis_client.get(_OPENED_KEY.format(key=key)):
            return CircuitState.HALF_OPEN
        return CircuitState.CLOSED

    # ── Call gate (raises when the circuit refuses the call) ────────────────

    async def check(self, key: str) -> None:
        state = await self.get_state(key)
        if state is CircuitState.OPEN:
            ttl = await redis_client.ttl(_STATE_KEY.format(key=key))
            raise ZohoCircuitOpenError(f"Zoho '{key}' circuit open; retry in ~{max(ttl, 0)}s")
        if state is CircuitState.HALF_OPEN:
            # Exactly one worker probes; everyone else keeps fast-failing.
            got_probe = await redis_client.set(_PROBE_KEY.format(key=key), "1", nx=True, ex=_PROBE_TTL)
            if not got_probe:
                raise ZohoCircuitOpenError(f"Zoho '{key}' circuit half-open; another worker is probing")
            logger.info("zoho_circuit_probe", key=key)

    # ── Outcome recording ────────────────────────────────────────────────────

    async def record_success(self, key: str, duration: float = 0.0) -> None:
        if await self.get_state(key) is CircuitState.HALF_OPEN:
            await self._close(key)
            return
        outcome = _OUTCOME_SLOW if duration >= settings.ZOHO_CB_SLOW_SECONDS else _OUTCOME_OK
        await self._record_and_evaluate(key, outcome)

    async def record_failure(self, key: str) -> None:
        if await self.get_state(key) is CircuitState.HALF_OPEN:
            logger.warning("zoho_circuit_probe_failed", key=key)
            await self._open(key)
            return
        await self._record_and_evaluate(key, _OUTCOME_FAIL)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _record_and_evaluate(self, key: str, outcome: str) -> None:
        now = time.time()
        cutoff = now - settings.ZOHO_CB_WINDOW_SECONDS
        member = f"{now}:{outcome}:{uuid.uuid4().hex[:8]}"  # nonce: no overwrites
        window_key = _WINDOW_KEY.format(key=key)

        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(window_key, "-inf", cutoff)   # purge stale
            pipe.zadd(window_key, {member: now})                # record outcome
            pipe.zrange(window_key, 0, -1)                      # read the window
            pipe.expire(window_key, settings.ZOHO_CB_WINDOW_SECONDS * 2)
            results = await pipe.execute()

        window: list[str] = results[2]
        total = len(window)
        if total < settings.ZOHO_CB_MIN_CALLS:
            return

        failures = sum(1 for m in window if m.split(":")[1] == _OUTCOME_FAIL)
        slow = sum(1 for m in window if m.split(":")[1] == _OUTCOME_SLOW)
        if (failures / total) >= settings.ZOHO_CB_FAILURE_RATE or (slow / total) >= settings.ZOHO_CB_SLOW_RATE:
            logger.error(
                "zoho_circuit_opened", key=key, window_calls=total,
                failures=failures, slow_calls=slow,
            )
            await self._open(key)

    async def _open(self, key: str) -> None:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.set(_STATE_KEY.format(key=key), CircuitState.OPEN.value,
                     ex=settings.ZOHO_CB_RECOVERY_SECONDS)
            # Marker outlives the state key so the lapse reads as HALF_OPEN;
            # bounded TTL prevents leaks if the group never gets traffic again.
            pipe.set(_OPENED_KEY.format(key=key), str(time.time()), ex=3600)
            pipe.delete(_WINDOW_KEY.format(key=key), _PROBE_KEY.format(key=key))
            await pipe.execute()

    async def _close(self, key: str) -> None:
        await redis_client.delete(
            _STATE_KEY.format(key=key),
            _OPENED_KEY.format(key=key),
            _WINDOW_KEY.format(key=key),
            _PROBE_KEY.format(key=key),
        )
        logger.info("zoho_circuit_closed", key=key)


zoho_circuit_breaker = ZohoCircuitBreaker()
