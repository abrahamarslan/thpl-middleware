"""Typed schema for logging configuration.

Pydantic validates the merged YAML so a typo in a config file fails loudly at
startup instead of silently producing wrong logging behaviour.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

LogFormat = Literal["json", "console"]
_VALID_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


def _normalise_level(value: str | None) -> str | None:
    if value is None:
        return None
    upper = value.upper()
    if upper not in _VALID_LEVELS:
        raise ValueError(f"Invalid log level {value!r}; expected one of {sorted(_VALID_LEVELS)}")
    return upper


class LoggerRule(BaseModel):
    """Per-namespace rule. Maps to a stdlib logger (e.g. 'app.zoho').

    A rule governs that logger AND its children via the stdlib logger
    hierarchy, so 'app.zoho' controls 'app.zoho.client', 'app.zoho.token', ...
    """

    model_config = {"extra": "forbid"}

    enabled: bool = True
    level: str | None = None          # None => inherit from root/parent
    propagate: bool = True

    @field_validator("level")
    @classmethod
    def _v_level(cls, v: str | None) -> str | None:
        return _normalise_level(v)


class LoggingConfig(BaseModel):
    """Fully-resolved logging configuration."""

    model_config = {"extra": "forbid"}

    # Master switch — false silences ALL application logging.
    enabled: bool = True

    # Root level + output format.
    level: str = "INFO"
    format: LogFormat = "json"

    utc: bool = True
    include_caller: bool = False      # add file:line:func (costly; dev/debug only)

    # Keys whose values are masked anywhere in a log event (defence in depth).
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "password", "passwd", "secret", "token", "access_token",
            "refresh_token", "authorization", "api_key", "client_secret",
            "set-cookie", "cookie",
        ]
    )

    # Named-logger / namespace rules (third-party + per-module).
    loggers: dict[str, LoggerRule] = Field(default_factory=dict)

    @field_validator("level")
    @classmethod
    def _v_level(cls, v: str) -> str:
        return _normalise_level(v)  # type: ignore[return-value]
