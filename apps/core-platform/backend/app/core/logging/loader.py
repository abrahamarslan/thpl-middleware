"""Load and merge layered logging configuration.

Reads the application base file, the active environment profile, and every
per-module file, deep-merging them in that order, then applies environment
variable overrides. The result is a validated LoggingConfig.

Resilient by design: a missing config directory or file falls back to code
defaults (so the app still logs even if configs are absent), but a malformed
file raises (fail fast on operator error).
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.conf import settings
from app.core.logging.schema import LoggingConfig

# backend/  (app/core/logging/loader.py -> parents[3])
_BASE_DIR = Path(__file__).resolve().parents[3]


def _resolve_config_dir() -> Path:
    raw = Path(settings.LOG_CONFIG_DIR)
    return raw if raw.is_absolute() else _BASE_DIR / raw


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Logging config {path} must be a mapping, got {type(data).__name__}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base` (override wins). Pure; copies."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_module_rules(modules_dir: Path) -> dict[str, Any]:
    """Each modules/*.yaml declares the namespace it governs via `logger:`.

        # modules/zoho.yaml
        logger: app.zoho
        enabled: true
        level: DEBUG
    """
    loggers: dict[str, Any] = {}
    if not modules_dir.is_dir():
        return loggers
    for path in sorted(modules_dir.glob("*.yaml")):
        raw = _read_yaml(path)
        namespace = raw.pop("logger", None)
        if not namespace:
            raise ValueError(f"Module logging file {path} must define a 'logger:' namespace")
        loggers[namespace] = _deep_merge(loggers.get(namespace, {}), raw)
    return {"loggers": loggers}


def _apply_env_overrides(merged: dict[str, Any]) -> dict[str, Any]:
    """Ops escape hatch: env vars (LOG_ENABLED / LOG_LEVEL / LOG_FORMAT) win
    over files, but ONLY when explicitly set. They are read through pydantic
    settings, so both real environment variables and backend/.env are honoured.
    """
    if settings.LOG_ENABLED is not None:
        merged["enabled"] = settings.LOG_ENABLED
    if settings.LOG_LEVEL:
        merged["level"] = settings.LOG_LEVEL
    if settings.LOG_FORMAT:
        merged["format"] = settings.LOG_FORMAT
    return merged


@lru_cache
def get_logging_config() -> LoggingConfig:
    """Resolve the effective LoggingConfig (cached for the process lifetime)."""
    config_dir = _resolve_config_dir()

    merged: dict[str, Any] = {}
    merged = _deep_merge(merged, _read_yaml(config_dir / "logging.yaml"))
    merged = _deep_merge(merged, _read_yaml(config_dir / "environments" / f"{settings.ENVIRONMENT}.yaml"))
    merged = _deep_merge(merged, _load_module_rules(config_dir / "modules"))
    merged = _apply_env_overrides(merged)

    return LoggingConfig.model_validate(merged)
