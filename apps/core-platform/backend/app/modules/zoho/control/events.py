"""Record-level sync events — "invoice 9549… was UPDATED: status, total".

Every committed change to a mirror row (and, later, every push outcome) writes
one ``zoho_sync_events`` row **in the same transaction** as the change, so an
event exists if and only if the change committed.

What is stored (docs/zoho-sync-implementation/sync-events.md):
  * mapped column names that changed and their old → new values, truncated to
    500 characters and **masked** for personal data (phone, email, GST/PAN,
    addresses keep only their last 4 characters);
  * never the Zoho payload, never secrets — the full document already lives in
    ``zoho_raw`` and its history in ClickHouse via CDC;
  * correlation: run id, request id, trace id, actor.

No-op applies (``unchanged``) are sampled (default 0 %) because they are the
bulk of every scan and carry no information.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from app.core.conf import settings
from app.modules.zoho.control.models import ZohoSyncEvent

#: Substrings of column names whose values are masked in diffs.
_MASKED_FIELD_MARKERS = (
    "email", "phone", "mobile", "gst", "pan_no", "tax_reg", "vat_reg",
    "address", "street", "zip", "attention", "bank", "card", "upi", "vpa",
)
_MAX_VALUE_CHARS = 500
_MAX_FIELDS_IN_DIFF = 50


def _serialise(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict | list):
        text = json.dumps(value, default=str, sort_keys=True)
    else:
        text = str(value)
    return text if len(text) <= _MAX_VALUE_CHARS else text[:_MAX_VALUE_CHARS] + "…"


def _mask(field: str, value: Any) -> Any:
    if value is None:
        return None
    lowered = field.lower()
    if not any(marker in lowered for marker in _MASKED_FIELD_MARKERS):
        return value
    text = str(value)
    return "•" * max(len(text) - 4, 0) + text[-4:] if len(text) > 4 else "••••"


def comparable(value: Any) -> Any:
    """Normalise values so 12.50 (Decimal) and 12.5 (float) are not "changes"."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def build_diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[str], dict[str, list[Any]]]:
    """Changed field names + ``{field: [old, new]}`` (serialised, masked, bounded)."""
    changed = sorted(f for f in after if comparable(before.get(f)) != comparable(after.get(f)))
    diff = {
        field: [_mask(field, _serialise(before.get(field))), _mask(field, _serialise(after.get(field)))]
        for field in changed[:_MAX_FIELDS_IN_DIFF]
    }
    return changed, diff


def enabled_for(event_type: str) -> bool:
    if not settings.ZOHO_SYNC_EVENTS_ENABLED:
        return False
    if event_type == "unchanged":
        rate = settings.ZOHO_SYNC_EVENTS_SAMPLE_UNCHANGED
        return rate > 0 and random.random() < rate
    return True


def new_event(
    *,
    module: str,
    event_type: str,
    direction: str = "pull",
    source: str | None = None,
    local_id: int | None = None,
    zoho_id: str | None = None,
    run_id: uuid.UUID | None = None,
    changed_fields: list[str] | None = None,
    diff: dict[str, Any] | None = None,
    zoho_last_modified_time: datetime | None = None,
    actor_user_id: int | None = None,
    error_category: str | None = None,
    error_fingerprint: str | None = None,
    message: str | None = None,
    command_id: int | None = None,
    inbox_id: int | None = None,
) -> ZohoSyncEvent:
    ctx = structlog.contextvars.get_contextvars()
    return ZohoSyncEvent(
        module=module,
        event_type=event_type,
        direction=direction,
        source=(source or "")[:48] or None,
        local_id=local_id,
        zoho_id=zoho_id,
        run_id=run_id,
        changed_fields=changed_fields or None,
        diff=diff or None,
        zoho_last_modified_time=zoho_last_modified_time,
        actor_user_id=actor_user_id,
        request_id=ctx.get("request_id"),
        trace_id=ctx.get("trace_id"),
        error_category=error_category,
        error_fingerprint=error_fingerprint,
        message=(message or None) and message[:2000],
        command_id=command_id,
        inbox_id=inbox_id,
    )


__all__ = ["build_diff", "comparable", "enabled_for", "new_event"]
