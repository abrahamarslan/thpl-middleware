"""Sensitive-data redaction processor.

Defence in depth: even if a developer accidentally logs a password, token or
Authorization header, the value is masked before it ever reaches stdout/Loki.
Matching is case-insensitive on the key name and recurses into nested dicts
and lists.
"""

from typing import Any

_MASK = "***REDACTED***"


def make_redaction_processor(redact_keys: list[str]):
    blocked = {k.lower() for k in redact_keys}

    def _scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (_MASK if isinstance(k, str) and k.lower() in blocked else _scrub(v))
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return type(value)(_scrub(v) for v in value)
        return value

    def processor(_logger, _method_name, event_dict: dict[str, Any]) -> dict[str, Any]:
        if not blocked:
            return event_dict
        return {
            k: (_MASK if k.lower() in blocked else _scrub(v))
            for k, v in event_dict.items()
        }

    return processor
