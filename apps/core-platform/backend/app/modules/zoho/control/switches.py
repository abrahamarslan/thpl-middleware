"""Engine switches — the operator's (and the engine's own) off buttons.

Checked by the transport **before any other gate**, so a paused engine spends
no quota, takes no rate tokens and never opens a circuit.

| Switch | Stored in | Set by | Blocks |
|---|---|---|---|
| ``engine_paused`` | system settings (audited) + Redis mirror | operator | all background traffic (pull and push); interactive still allowed |
| ``pull_enabled`` = false | same | operator | background reads |
| ``push_enabled`` = false | same | operator | every write (interactive included — a push is a push) |
| ``webhooks_enabled`` = false | same | operator | webhook processing (checked by the inbox, Phase 7) |
| ``paused_modules`` | same | operator | background traffic for those modules |
| ``auth_paused`` | Redis only | token manager on ``invalid_code`` | **everything** — there is no valid credential; cleared on reconnect |

Durable switches live in the hierarchical settings module (one key each, so
every change lands in ``setting_audit_logs`` with actor and IP). A Redis hash
mirrors them for cheap per-call reads, and each process caches the snapshot
for ``ZOHO_SWITCH_CACHE_SECONDS``. If Redis loses the mirror (eviction,
restart) it is rebuilt from Postgres on the next read.

A refused call raises ``ZohoEngineDisabled`` — a kind of ``ZohoBudgetDeferred``,
so lanes and the outbox already know to yield and come back later.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.db import async_session_factory
from app.database.redis import redis_client
from app.modules.zoho.core.errors import ZohoBudgetDeferred

logger = structlog.get_logger("app.zoho.switches")

Direction = Literal["pull", "push"]

_MIRROR_KEY = "zoho:control:switches"
_AUTH_PAUSE_KEY = "zoho:control:auth_paused"

#: Durable switches → (settings key, default)
DURABLE_SWITCHES: dict[str, tuple[str, Any]] = {
    "engine_paused": ("zoho.control.engine_paused", False),
    "pull_enabled": ("zoho.control.pull_enabled", True),
    "push_enabled": ("zoho.control.push_enabled", True),
    "webhooks_enabled": ("zoho.control.webhooks_enabled", False),
    "paused_modules": ("zoho.control.paused_modules", []),
}


class ZohoEngineDisabled(ZohoBudgetDeferred):
    """A switch refuses this call. Background work yields; users see 503."""

    status_code = 503
    code = "zoho_engine_disabled"


@dataclass(frozen=True, slots=True)
class SwitchState:
    engine_paused: bool = False
    pull_enabled: bool = True
    push_enabled: bool = True
    webhooks_enabled: bool = False
    paused_modules: frozenset[str] = frozenset()
    auth_paused: bool = False
    auth_paused_reason: str | None = None
    source: str = "defaults"                       # redis | database | defaults
    loaded_at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine_paused": self.engine_paused,
            "pull_enabled": self.pull_enabled,
            "push_enabled": self.push_enabled,
            "webhooks_enabled": self.webhooks_enabled,
            "paused_modules": sorted(self.paused_modules),
            "auth_paused": self.auth_paused,
            "auth_paused_reason": self.auth_paused_reason,
            "source": self.source,
        }

    def refusal(self, *, direction: Direction, module: str | None, interactive: bool) -> str | None:
        """The switch that blocks this call, or None if it may proceed."""
        if self.auth_paused:
            return "auth_paused"
        if direction == "push" and not self.push_enabled:
            return "push_disabled"
        if interactive:
            return None
        if self.engine_paused:
            return "engine_paused"
        if direction == "pull" and not self.pull_enabled:
            return "pull_disabled"
        if module and module in self.paused_modules:
            return f"module_paused:{module}"
        return None


def _decode(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class EngineSwitches:
    def __init__(self, *, redis=None, session_factory=None, cache_seconds: float | None = None) -> None:
        self._redis = redis if redis is not None else redis_client
        self._session_factory = session_factory or async_session_factory
        self._cache_seconds = settings.ZOHO_SWITCH_CACHE_SECONDS if cache_seconds is None else cache_seconds
        self._cached: SwitchState | None = None

    def bind_session_factory(self, session_factory) -> None:
        """Celery tasks pass their own engine (see auth.CredentialStore)."""
        self._session_factory = session_factory

    def invalidate(self) -> None:
        self._cached = None

    # ── reads ───────────────────────────────────────────────────────────────

    async def snapshot(self) -> SwitchState:
        cached = self._cached
        if cached and (time.monotonic() - cached.loaded_at) < self._cache_seconds:
            return cached

        state = await self._load_from_redis()
        if state is None:
            durable = await self._load_from_database()
            state = self._build(durable or {}, source="database" if durable is not None else "defaults")
            if durable is not None:
                await self._write_mirror(durable)
            auth = await self._auth_pause()
            if auth:
                state = self._build(durable or {}, source=state.source, auth=auth)

        self._cached = state
        return state

    async def check(self, *, direction: Direction, module: str | None, interactive: bool) -> None:
        """Raise ``ZohoEngineDisabled`` when a switch forbids this call."""
        state = await self.snapshot()
        reason = state.refusal(direction=direction, module=module, interactive=interactive)
        if reason:
            raise ZohoEngineDisabled(
                f"Zoho {direction} traffic is disabled ({reason})",
                reason=f"switch:{reason}",
                module=module,
                data={"switch": reason, "direction": direction},
            )

    async def _load_from_redis(self) -> SwitchState | None:
        try:
            mirror = await self._redis.hgetall(_MIRROR_KEY)
            auth = await self._auth_pause()
        except RedisError as exc:
            logger.warning("zoho.switches.redis_unavailable", error=str(exc))
            return None
        if not mirror or mirror.get("loaded") != "1":
            return None
        durable = {name: _decode(mirror.get(name), default) for name, (_, default) in DURABLE_SWITCHES.items()}
        return self._build(durable, source="redis", auth=auth)

    async def _load_from_database(self) -> dict[str, Any] | None:
        from app.modules.system.service import system_settings_service

        try:
            async with self._session_factory() as db:
                values: dict[str, Any] = {}
                for name, (key, default) in DURABLE_SWITCHES.items():
                    value = await system_settings_service.get_setting(db, key)
                    values[name] = default if value is None else value
                return values
        except Exception as exc:  # noqa: BLE001 — never let switch storage break the engine
            logger.error("zoho.switches.database_unavailable", error=str(exc))
            return None

    async def _auth_pause(self) -> dict[str, Any] | None:
        try:
            raw = await self._redis.get(_AUTH_PAUSE_KEY)
        except RedisError:
            return None
        return _decode(raw, None) if raw else None

    @staticmethod
    def _build(durable: dict[str, Any], *, source: str, auth: dict[str, Any] | None = None) -> SwitchState:
        def flag(name: str) -> bool:
            value = durable.get(name, DURABLE_SWITCHES[name][1])
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)

        modules = durable.get("paused_modules") or []
        if isinstance(modules, str):
            modules = [m.strip() for m in modules.split(",") if m.strip()]
        return SwitchState(
            engine_paused=flag("engine_paused"),
            pull_enabled=flag("pull_enabled"),
            push_enabled=flag("push_enabled"),
            webhooks_enabled=flag("webhooks_enabled"),
            paused_modules=frozenset(modules),
            auth_paused=bool(auth),
            auth_paused_reason=(auth or {}).get("reason"),
            source=source,
        )

    # ── writes ──────────────────────────────────────────────────────────────

    async def set(self, db: AsyncSession, name: str, value: Any, *, actor: str,
                  ip_address: str | None = None) -> SwitchState:
        """Operator change: audited in Postgres, mirrored to Redis, cache dropped."""
        if name not in DURABLE_SWITCHES:
            raise ValueError(f"unknown switch '{name}'")
        key, default = DURABLE_SWITCHES[name]
        if isinstance(default, bool) and not isinstance(value, bool):
            raise ValueError(f"switch '{name}' takes a boolean")
        if isinstance(default, list):
            value = sorted({str(v) for v in value})

        from app.modules.system.service import system_settings_service

        await system_settings_service.set_setting(db, key, value, updated_by=actor, ip_address=ip_address)
        await db.flush()

        current = await self._load_from_redis()
        durable = (
            {k: getattr(current, k) if k != "paused_modules" else sorted(current.paused_modules)
             for k in DURABLE_SWITCHES}
            if current else {n: d for n, (_, d) in DURABLE_SWITCHES.items()}
        )
        durable[name] = value
        await self._write_mirror(durable)
        self.invalidate()
        logger.warning("zoho.switches.changed", switch=name, value=value, actor=actor)
        return await self.snapshot()

    async def _write_mirror(self, durable: dict[str, Any]) -> None:
        try:
            mapping = {name: json.dumps(durable.get(name, default)) for name, (_, default) in DURABLE_SWITCHES.items()}
            mapping["loaded"] = "1"
            await self._redis.hset(_MIRROR_KEY, mapping=mapping)
        except RedisError as exc:
            logger.warning("zoho.switches.mirror_write_failed", error=str(exc))

    async def set_auth_paused(self, reason: str) -> None:
        """Automatic: the refresh token is gone. Everything stops until reconnect."""
        payload = json.dumps({"reason": reason, "at": datetime.now(UTC).isoformat()})
        try:
            await self._redis.set(_AUTH_PAUSE_KEY, payload)
        except RedisError as exc:
            logger.error("zoho.switches.auth_pause_failed", error=str(exc))
        self.invalidate()
        logger.critical("zoho.switches.auth_paused", reason=reason)

    async def clear_auth_paused(self) -> None:
        try:
            removed = await self._redis.delete(_AUTH_PAUSE_KEY)
        except RedisError:
            removed = 0
        self.invalidate()
        if removed:
            logger.warning("zoho.switches.auth_resumed")


zoho_switches = EngineSwitches()

__all__ = [
    "DURABLE_SWITCHES",
    "Direction",
    "EngineSwitches",
    "SwitchState",
    "ZohoEngineDisabled",
    "zoho_switches",
]
