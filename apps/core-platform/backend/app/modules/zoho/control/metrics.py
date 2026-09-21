"""Zoho gauges on the backend's /metrics — fed from the planner's snapshot.

The planner publishes one JSON snapshot to Redis every minute
(``zoho:health``). A small background task in the API process copies it into
Prometheus gauges every 15 s, so a scrape never runs SQL or talks to Zoho,
and the numbers are consistent with what the planner decided on.

Gauges (all prefixed ``zoho_``):

| Gauge | Labels | Meaning |
|---|---|---|
| quota_used / quota_remaining / quota_limit | pool | today's spend vs the ceiling |
| quota_state | pool | 0 open · 1 conserve · 2 essential · 3 reserved_only · 4 exhausted |
| quota_background_allowance | pool | pacing-curve allowance right now |
| rate_tokens, inflight | — | minute bucket level, org-wide calls in flight |
| switch | name | 1 when the switch is ON (engine_paused, auth_paused, …) |
| token_ttl_seconds, token_refreshes_in_window | — | OAuth health |
| planner_last_tick_timestamp, planner_running_runs | — | planner liveness |
| health_snapshot_age_seconds | — | staleness of all of the above |
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import structlog
from prometheus_client import Gauge
from redis.exceptions import RedisError

from app.database.redis import redis_client
from app.modules.zoho.control.planner import HEALTH_KEY

logger = structlog.get_logger("app.zoho.metrics")

STATE_CODE = {"open": 0, "conserve": 1, "essential": 2, "reserved_only": 3, "exhausted": 4}

QUOTA_USED = Gauge("zoho_quota_used", "Zoho calls spent in the current quota day", ["pool"])
QUOTA_REMAINING = Gauge("zoho_quota_remaining", "Zoho calls left before the daily ceiling", ["pool"])
QUOTA_LIMIT = Gauge("zoho_quota_limit", "Configured daily Zoho call ceiling", ["pool"])
QUOTA_STATE = Gauge("zoho_quota_state", "Governor state (0 open … 4 exhausted)", ["pool"])
QUOTA_ALLOWANCE = Gauge("zoho_quota_background_allowance", "Background pacing allowance now", ["pool"])
RATE_TOKENS = Gauge("zoho_rate_tokens", "Per-minute token bucket level")
INFLIGHT = Gauge("zoho_inflight", "Zoho calls in flight org-wide")
SWITCH = Gauge("zoho_switch", "1 when an engine switch is ON", ["name"])
TOKEN_TTL = Gauge("zoho_token_ttl_seconds", "Seconds until the cached access token expires")
TOKEN_REFRESHES = Gauge("zoho_token_refreshes_in_window", "Token refreshes in the current 10-minute window")
PLANNER_LAST_TICK = Gauge("zoho_planner_last_tick_timestamp", "Unix time of the last planner tick")
PLANNER_RUNNING = Gauge("zoho_planner_running_runs", "Zoho sync runs currently running")
SNAPSHOT_AGE = Gauge("zoho_health_snapshot_age_seconds", "Age of the planner health snapshot")


def apply_snapshot(payload: dict, *, now: datetime | None = None) -> None:
    """Copy one planner snapshot into the gauges (pure; unit-tested)."""
    now = now or datetime.now(UTC)
    gov = payload.get("governor") or {}
    pool = gov.get("pool", "zoho")
    QUOTA_USED.labels(pool).set(gov.get("used", 0))
    QUOTA_REMAINING.labels(pool).set(gov.get("remaining", 0))
    QUOTA_LIMIT.labels(pool).set(gov.get("daily_hard_limit", 0))
    QUOTA_STATE.labels(pool).set(STATE_CODE.get(gov.get("state", "open"), 0))
    QUOTA_ALLOWANCE.labels(pool).set(gov.get("background_allowance", 0))
    RATE_TOKENS.set(gov.get("rate_tokens") or 0)
    INFLIGHT.set(gov.get("inflight", 0))

    switches = payload.get("switches") or {}
    SWITCH.labels("engine_paused").set(1 if switches.get("engine_paused") else 0)
    SWITCH.labels("pull_disabled").set(0 if switches.get("pull_enabled", True) else 1)
    SWITCH.labels("push_disabled").set(0 if switches.get("push_enabled", True) else 1)
    SWITCH.labels("auth_paused").set(1 if switches.get("auth_paused") else 0)
    SWITCH.labels("modules_paused").set(len(switches.get("paused_modules") or []))

    token = payload.get("token") or {}
    TOKEN_TTL.set(token.get("token_ttl_seconds", 0))
    TOKEN_REFRESHES.set(token.get("refreshes_in_window", 0))

    planner = payload.get("planner") or {}
    PLANNER_RUNNING.set(planner.get("running", 0))
    last_tick = payload.get("planner_last_tick")
    if last_tick:
        tick_at = datetime.fromisoformat(last_tick)
        PLANNER_LAST_TICK.set(tick_at.timestamp())
        SNAPSHOT_AGE.set(max((now - tick_at).total_seconds(), 0))


async def refresh_forever(interval: float = 15.0) -> None:
    """API-lifespan background task. Never raises; logs once per failure streak."""
    failing = False
    while True:
        try:
            raw = await redis_client.get(HEALTH_KEY)
            if raw:
                apply_snapshot(json.loads(raw))
            failing = False
        except asyncio.CancelledError:
            raise
        except (RedisError, ValueError, TypeError) as exc:
            if not failing:
                logger.warning("zoho.metrics.refresh_failed", error=str(exc))
            failing = True
        await asyncio.sleep(interval)


__all__ = ["apply_snapshot", "refresh_forever"]
