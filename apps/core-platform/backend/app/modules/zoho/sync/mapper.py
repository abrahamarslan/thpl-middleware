"""Field-mapping engine — Zoho payload <-> local column dicts.

Design rules (the "sync must never fail on data" doctrine):
  - a MISSING key is skipped, never written as NULL — partial payloads
    (index rows vs detail rows) can't erase data already synced;
  - a transform failure logs and skips that one field, it never aborts the
    record (every business column is nullable by schema rule);
  - outbound building drops None values by default — Zoho rejects explicit
    nulls on many endpoints.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from app.modules.zoho.sync.config import FieldMapping, ModuleSyncConfig

logger = structlog.get_logger("app.zoho.sync.mapper")

#: Sentinel distinguishing "key absent" from "key present with null value".
MISSING = object()


# ── Transforms ───────────────────────────────────────────────────────────────

def parse_zoho_datetime(value: Any) -> datetime | None:
    """Parse Zoho timestamps: ISO 8601 ``2016-06-11T17:38:06-0700`` or dates.

    Returns tz-aware datetimes (UTC assumed when Zoho omits the offset).
    """
    if value in (None, "", " "):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:  # bare date, e.g. account_created_date "2016-02-18"
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_zoho_date(value: Any) -> date | None:
    dt = parse_zoho_datetime(value)
    return dt.date() if dt else None


def _to_bool(value: Any) -> bool | None:
    if value in (None, "", " "):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "y", "active")


def _to_int(value: Any) -> int | None:
    if value in (None, "", " "):
        return None
    return int(float(value))


def _to_float(value: Any) -> float | None:
    if value in (None, "", " "):
        return None
    return float(value)


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, "", " "):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


#: Named coercions referenced by FieldMapping.transform.
TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "str": _to_str,
    "int": _to_int,
    "float": _to_float,
    "bool": _to_bool,
    "decimal": _to_decimal,
    "zoho_datetime": parse_zoho_datetime,
    "zoho_date": parse_zoho_date,
}


def register_transform(name: str, fn: Callable[[Any], Any]) -> None:
    """Modules may register domain-specific transforms before use."""
    TRANSFORMS[name] = fn


# ── Payload access ───────────────────────────────────────────────────────────

def extract(payload: dict, dotted: str) -> Any:
    """Safe dotted-path lookup: extract({"a": {"b": 1}}, "a.b") -> 1.

    Returns the MISSING sentinel when any segment is absent or a parent is
    not a dict — the caller decides whether to skip or default.
    """
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def _assign(target: dict, dotted: str, value: Any) -> None:
    """Set a dotted path on a nested dict, creating intermediate levels."""
    parts = dotted.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


# ── Mapping ──────────────────────────────────────────────────────────────────

def map_inbound(config: ModuleSyncConfig, payload: dict) -> dict[str, Any]:
    """Zoho payload -> {local_column: value} using the module's field map."""
    values: dict[str, Any] = {}
    for mapping in config.field_map:
        raw = extract(payload, mapping.zoho)
        if raw is MISSING:
            if mapping.apply_default_when_missing:
                values[mapping.local] = mapping.default
            continue
        values[mapping.local] = _coerce(config.module, mapping, raw)
    return values


def _coerce(module: str, mapping: FieldMapping, raw: Any) -> Any:
    if raw is None:
        return mapping.default
    if mapping.transform is None:
        return raw
    fn = TRANSFORMS.get(mapping.transform)
    if fn is None:
        logger.warning("unknown_transform", module=module, transform=mapping.transform, field=mapping.local)
        return raw
    try:
        result = fn(raw)
        return mapping.default if result is None else result
    except Exception:  # noqa: BLE001 — one bad field never sinks the record
        logger.warning("transform_failed", module=module, field=mapping.local,
                       transform=mapping.transform, raw=repr(raw)[:120])
        return mapping.default


def map_outbound(config: ModuleSyncConfig, row: Any, *, include_none: bool = False) -> dict:
    """Local ORM row -> Zoho write payload (reverse of map_inbound).

    Only mappings flagged ``outbound`` participate; dotted Zoho paths are
    rebuilt as nested objects (``address.city`` -> {"address": {"city": ...}}).
    """
    payload: dict[str, Any] = {}
    for mapping in config.field_map:
        if not mapping.outbound:
            continue
        value = getattr(row, mapping.local, None)
        if value is None and not include_none:
            continue
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        _assign(payload, mapping.outbound_key or mapping.zoho, value)
    return payload


def flatten_custom_fields(payload: dict) -> dict[str, str] | None:
    """Zoho's custom_fields array -> flat hstore-friendly {api_name: str(value)}.

    Zoho shape: [{"customfield_id": ..., "api_name": "cf_x", "label": "X",
    "value": ...}, ...]. hstore values must be text; complex values are
    stringified (the untouched array is always available in zoho_raw).
    """
    raw = payload.get("custom_fields")
    if not isinstance(raw, list) or not raw:
        return None
    flat: dict[str, str] = {}
    for field in raw:
        if not isinstance(field, dict):
            continue
        key = field.get("api_name") or field.get("label") or field.get("customfield_id")
        if key is None:
            continue
        value = field.get("value")
        flat[str(key)] = "" if value is None else str(value)
    return flat or None
