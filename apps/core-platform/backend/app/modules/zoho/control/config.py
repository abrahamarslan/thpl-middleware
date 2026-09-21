"""Config resolver — runtime per-module overrides of the sync knobs.

Layers, most specific wins (docs/zoho-sync-implementation/config-resolver.md):

| Layer | Source | Changed by |
|---|---|---|
| L0 code default | ``GlobalSyncDefaults`` field defaults | a release |
| L1 environment | ``ZOHO_SYNC_*`` in ``conf.py`` | a redeploy |
| L2 module | the module's ``resolve_module_config(...)`` declaration | a release |
| L3 override | system settings ``zoho.module.<module>.<knob>`` | an operator, at runtime (audited) |

Only knobs in :data:`KNOBS` can be overridden, each with a type and bounds —
identity (endpoint, id attribute, field map) never changes at runtime. One
setting row per knob (the settings table caps values at 500 chars; N18).

Reads are cached per process and re-checked against a Redis version counter
(``zoho:cfg:version``) at most every ``ZOHO_CONFIG_CACHE_SECONDS``; a write
bumps the counter, so every worker picks the change up within that window.
If Redis is down the cache is reloaded from Postgres at most once a minute;
if Postgres is down the last good overrides stay in force.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.zoho.sync.config import GlobalSyncDefaults, ModuleSyncConfig, sync_defaults

logger = structlog.get_logger("app.zoho.config")

KEY_PREFIX = "zoho.module."
VERSION_KEY = "zoho:cfg:version"
_REDIS_DOWN_RELOAD_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class Knob:
    type: type
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    help: str = ""

    def coerce(self, raw: Any) -> Any:
        """Parse (from API JSON or a stored string) and bounds-check."""
        value = raw
        if self.type is bool:
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                    raise ValueError("expected a boolean")
                value = lowered in ("true", "1", "yes", "on")
            elif not isinstance(raw, bool):
                raise ValueError("expected a boolean")
        elif self.type is int:
            if isinstance(raw, bool):
                raise ValueError("expected an integer")
            value = int(raw) if isinstance(raw, str) else raw
            if not isinstance(value, int):
                raise ValueError("expected an integer")
        elif self.type is float:
            if isinstance(raw, bool):
                raise ValueError("expected a number")
            value = float(raw)
        elif self.type is list:
            value = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise ValueError("expected a list of non-empty strings")
        elif self.type is str:
            value = str(raw)
        if self.choices is not None and value not in self.choices:
            raise ValueError(f"must be one of {', '.join(self.choices)}")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"must be >= {self.minimum:g}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"must be <= {self.maximum:g}")
        return value

    def stored(self, value: Any) -> Any:
        """What the settings service persists (lists as JSON text)."""
        return json.dumps(value) if self.type is list else value


#: The runtime-tunable knobs. Bounds are floors/ceilings no operator can cross.
KNOBS: dict[str, Knob] = {
    "enabled": Knob(bool, help="Pull this module at all"),
    "strategy": Knob(str, choices=("full", "incremental", "index"), help="Scheduled-lane strategy"),
    "sync_interval_minutes": Knob(int, 1, 10_080, help="Scheduled-lane cadence"),
    "weekly_full_enabled": Knob(bool, help="Include in the weekly full reconcile"),
    "batch_size": Knob(int, 1, 200, help="Records per list page (Zoho max 200)"),
    "detail_dispatch": Knob(str, choices=("inline", "queued"), help="N+1 detail fetch mode"),
    "wait_between_calls": Knob(float, 0.0, 10.0, help="Seconds between inline detail calls"),
    # Stop budgets. max_run_seconds is capped below Celery's soft time limit (540 s).
    "max_run_seconds": Knob(int, 10, 480, help="Slice wall-clock budget"),
    "max_pages_per_run": Knob(int, 0, 100_000, help="Slice page budget (0 = none)"),
    "max_records_per_run": Knob(int, 0, 10_000_000, help="Slice record budget (0 = none)"),
    "soft_delete_missing": Knob(bool, help="Full scans tombstone rows Zoho no longer lists (also needs the env switch)"),
    "hash_volatile_keys": Knob(list, help="Payload keys ignored by the no-op hash (glob)"),
}


def setting_key(module: str, knob: str) -> str:
    return f"{KEY_PREFIX}{module}.{knob}"


class ConfigError(ValueError):
    """An override was refused (unknown module/knob, wrong type, out of bounds)."""


class ConfigResolver:
    def __init__(self, *, redis=None, cache_seconds: float | None = None) -> None:
        self._redis = redis if redis is not None else redis_client
        self._cache_seconds = settings.ZOHO_CONFIG_CACHE_SECONDS if cache_seconds is None else cache_seconds
        self._overrides: dict[str, dict[str, Any]] | None = None
        self._version: str | None = None
        self._checked_at = 0.0
        self._loaded_at = 0.0

    def invalidate(self) -> None:
        self._overrides = None

    # ── reads ───────────────────────────────────────────────────────────────

    async def overrides(self, db: AsyncSession) -> dict[str, dict[str, Any]]:
        """All L3 overrides: ``{module: {knob: value}}`` (cached)."""
        now = time.monotonic()
        if self._overrides is not None and now - self._checked_at < self._cache_seconds:
            return self._overrides

        version = await self._current_version()
        if self._overrides is not None:
            unchanged = version is not None and version == self._version
            redis_down_but_fresh = version is None and now - self._loaded_at < _REDIS_DOWN_RELOAD_SECONDS
            if unchanged or redis_down_but_fresh:
                self._checked_at = now
                return self._overrides

        try:
            loaded = await self._load(db)
        except Exception as exc:  # noqa: BLE001 — keep the last good config
            logger.error("zoho.config.load_failed", error=str(exc))
            self._checked_at = now
            return self._overrides or {}
        self._overrides, self._version = loaded, version
        self._checked_at = self._loaded_at = now
        return loaded

    async def effective(self, db: AsyncSession, defn) -> ModuleSyncConfig:
        """The module's config with its overrides applied (same object if none)."""
        module_overrides = (await self.overrides(db)).get(defn.name)
        if not module_overrides:
            return defn.config
        return defn.config.model_copy(update=module_overrides)

    async def describe(self, db: AsyncSession, defn) -> dict[str, dict[str, Any]]:
        """Every knob: effective value and the layer that supplied it."""
        module_overrides = (await self.overrides(db)).get(defn.name, {})
        code_defaults = GlobalSyncDefaults()
        described = {}
        for name, knob in KNOBS.items():
            module_value = _plain(getattr(defn.config, name))
            if name in module_overrides:
                value, layer = module_overrides[name], "override"
            elif module_value != _plain(getattr(sync_defaults, name)):
                value, layer = module_value, "module"
            elif module_value != _plain(getattr(code_defaults, name)):
                value, layer = module_value, "environment"
            else:
                value, layer = module_value, "default"
            described[name] = {
                "value": _plain(value), "layer": layer, "declared": module_value,
                "type": knob.type.__name__, "min": knob.minimum, "max": knob.maximum,
                "choices": list(knob.choices) if knob.choices else None, "help": knob.help,
            }
        return described

    async def _current_version(self) -> str | None:
        try:
            raw = await self._redis.get(VERSION_KEY)
        except (RedisError, RuntimeError, OSError):   # down, or a pool bound to a dead loop
            return None
        return str(raw or "0")

    async def _load(self, db: AsyncSession) -> dict[str, dict[str, Any]]:
        from app.modules.system.model import SettingContext, SettingDefinition, SettingValue

        rows = await db.execute(
            select(SettingDefinition.key, SettingValue.value)
            .join(SettingValue, SettingValue.definition_id == SettingDefinition.id)
            .where(SettingDefinition.key.like(f"{KEY_PREFIX}%"),
                   SettingValue.context_type == SettingContext.GLOBAL,
                   SettingValue.context_id.is_(None))
        )
        result: dict[str, dict[str, Any]] = {}
        for key, raw in rows:
            module, _, knob = key[len(KEY_PREFIX):].rpartition(".")
            if knob not in KNOBS or not module:
                continue
            try:
                value = KNOBS[knob].coerce(raw)
            except (ValueError, TypeError) as exc:
                # A bad stored value must not break every sync — ignore it loudly.
                logger.error("zoho.config.bad_override", key=key, value=raw, error=str(exc))
                continue
            if knob == "strategy":
                from app.modules.zoho.sync.config import SyncStrategyName

                value = SyncStrategyName(value)
            result.setdefault(module, {})[knob] = value
        return result

    # ── writes ──────────────────────────────────────────────────────────────

    async def set(self, db: AsyncSession, defn, knob: str, raw: Any, *, actor: str,
                  ip_address: str | None = None) -> Any:
        """Validate, persist (audited), commit, bump the version. Returns the value.

        Commits ``db``: an override is its own transaction."""
        from app.modules.system.service import system_settings_service

        if knob not in KNOBS:
            raise ConfigError(f"'{knob}' is not a runtime knob; allowed: {', '.join(sorted(KNOBS))}")
        spec = KNOBS[knob]
        try:
            value = spec.coerce(raw)
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"{knob}: {exc}") from None
        stored = spec.stored(value)
        if isinstance(stored, str) and len(stored) > 500:
            raise ConfigError(f"{knob}: value longer than 500 characters")

        # The whole candidate must still be a valid module config.
        current = (await self.overrides(db)).get(defn.name, {})
        candidate = {**defn.config.model_dump(), **current, knob: value}
        try:
            ModuleSyncConfig.model_validate(candidate)
        except ValidationError as exc:
            raise ConfigError(f"{knob}: {exc.errors()[0]['msg']}") from None

        await system_settings_service.set_setting(
            db, setting_key(defn.name, knob), stored, updated_by=actor, ip_address=ip_address
        )
        # Commit BEFORE bumping the version: a worker that reloads on the new
        # version must see the new row, or it would cache the old value under
        # the new version until the next change (ERRORS E20).
        await db.commit()
        await self._bump()
        logger.warning("zoho.config.override_set", module=defn.name, knob=knob, value=value, actor=actor)
        return value

    async def clear(self, db: AsyncSession, defn, knob: str, *, actor: str,
                    ip_address: str | None = None) -> bool:
        """Remove an override (audited); the module falls back to its declared value.

        Deleting the value row, not writing the default: the settings service
        would otherwise keep answering with the definition's first-ever value.
        """
        from app.modules.system.model import SettingAuditLog, SettingContext, SettingDefinition, SettingValue

        if knob not in KNOBS:
            raise ConfigError(f"'{knob}' is not a runtime knob")
        key = setting_key(defn.name, knob)
        value_row = await db.scalar(
            select(SettingValue)
            .join(SettingDefinition, SettingValue.definition_id == SettingDefinition.id)
            .where(SettingDefinition.key == key, SettingValue.context_type == SettingContext.GLOBAL,
                   SettingValue.context_id.is_(None))
        )
        if value_row is None:
            return False
        db.add(SettingAuditLog(
            setting_value_id=None, module_name=key.split(".", 1)[0], definition_key=key,
            context_type=SettingContext.GLOBAL, context_id=None, old_value=value_row.value,
            new_value="(override removed)", changed_by=actor, ip_address=ip_address,
        ))
        await db.delete(value_row)
        await db.commit()
        await self._bump()
        logger.warning("zoho.config.override_cleared", module=defn.name, knob=knob, actor=actor)
        return True

    async def _bump(self) -> None:
        self.invalidate()
        try:
            await self._redis.incr(VERSION_KEY)
        except RedisError as exc:
            logger.warning("zoho.config.version_bump_failed", error=str(exc))


def _plain(value: Any) -> Any:
    return getattr(value, "value", value)


zoho_config = ConfigResolver()

__all__ = [
    "KEY_PREFIX",
    "KNOBS",
    "VERSION_KEY",
    "ConfigError",
    "ConfigResolver",
    "Knob",
    "setting_key",
    "zoho_config",
]
