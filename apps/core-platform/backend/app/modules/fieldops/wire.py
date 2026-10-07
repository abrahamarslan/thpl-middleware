"""The inbound mapper of the location stream — every ping item passes here BEFORE ``PingIn`` validates it
(docs/fieldops/android-contract.md §3; the "mapper at every inbound boundary" rule).

Two spellings reach ONE model:

* the native ``PingIn`` shape (``uuid``, ``client_timestamp``, ``accuracy_m``, ``kind`` + ``checkpoint_label``);
* the Android guide's §6 ``PingDto`` shape (``ping_id``, ``captured_at``, ``accuracy``, ``capture_reason`` …).

The Android shape is renamed field by field; ``capture_reason`` becomes ``kind`` + ``checkpoint_label``;
``elapsed_realtime_ns`` becomes milliseconds; ``geofence_event`` becomes ``geofence_uuid`` + a geofence
label. Server-owned or per-session fields (``received_at``, ``device_model``, ``os_version``,
``app_version_code``) are DROPPED — the server sets the first, ``POST /me/devices`` carries the rest.
Anything else unknown (camelCase Room-entity keys such as ``pingId``, ``syncStatus``) REJECTS the item
with the offending names, so a client serialising the wrong object finds out on the first upload.

Owner check: when an item names its user (``da_id`` / ``user_ref``) it must be the token's user (id,
uuid, username or employee code). On a shared phone, a queue left by the previous user must never be
flushed under the next user's token.

PURE — no I/O; table-tested in ``tests/test_fieldops_wire.py``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from app.modules.fieldops.enums import CheckpointLabel, NetworkType, PingKind

#: Android ``capture_reason`` → (kind, checkpoint_label).
CAPTURE_REASONS: dict[str, tuple[str, str | None]] = {
    "interval": (PingKind.CONTINUOUS.value, None),
    "shift_start": (PingKind.CHECKPOINT.value, CheckpointLabel.SHIFT_START.value),
    "shift_end": (PingKind.CHECKPOINT.value, CheckpointLabel.SHIFT_END.value),
    "start_delivery": (PingKind.CHECKPOINT.value, CheckpointLabel.VISIT_START.value),
    "end_delivery": (PingKind.CHECKPOINT.value, CheckpointLabel.VISIT_END.value),
    "geofence_enter": (PingKind.CHECKPOINT.value, CheckpointLabel.GEOFENCE_ENTER.value),
    "geofence_exit": (PingKind.CHECKPOINT.value, CheckpointLabel.GEOFENCE_EXIT.value),
}

#: Android name → native name (straight renames).
RENAMES = {
    "ping_id": "uuid", "captured_at": "client_timestamp", "accuracy": "accuracy_m", "speed": "speed_mps",
    "is_mock_location": "is_mock", "shift_id": "shift_uuid", "stop_id": "visit_uuid",
    "is_significant": "client_significant", "distance_from_last_m": "client_distance_m",
}
#: Same name on both sides.
PASSTHROUGH = {"latitude", "longitude", "provider", "battery_pct", "activity_type", "activity_confidence",
               "battery_state", "app_state", "network_type", "altitude_m", "sequence_no", "boot_count",
               "satellites", "visit_uuid", "shift_uuid"}
#: Accepted and dropped: server-owned (``received_at``) or per-session (POST /me/devices).
DROPPED = {"received_at", "device_model", "os_version", "app_version_code"}
#: Keys that mark an item as the Android §6 shape.
ANDROID_MARKERS = {"ping_id", "captured_at", "capture_reason", "elapsed_realtime_ns", "is_mock_location"}
_OWNER_KEYS = ("da_id", "user_ref")
_NETWORK = {n.value for n in NetworkType}


class WireError(ValueError):
    """One item cannot be accepted; ``str()`` is the per-item rejection reason."""


def owner_ids(user: Any, extra: Iterable[str | None] = ()) -> frozenset[str]:
    ids = {str(user.id)}
    for value in (getattr(user, "uuid", None), getattr(user, "username", None), *extra):
        if value:
            ids.add(str(value))
    return frozenset(i.strip().lower() for i in ids)


def _timestamp(value: Any) -> Any:
    """ISO-8601 passes through; a number is epoch MILLISECONDS (an Android ``…EpochMs`` value)."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.UTC).isoformat()
    return value


def _network(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text if text in _NETWORK else NetworkType.UNKNOWN.value


def normalize(raw: Any, *, owners: frozenset[str] | None = None) -> dict[str, Any]:
    """One ping item → the native ``PingIn`` dict. Raises :class:`WireError` (the rejection reason)."""
    if not isinstance(raw, dict):
        raise WireError("item is not an object")
    claimed = next((raw[k] for k in _OWNER_KEYS if raw.get(k) is not None), None)
    if claimed is not None and owners is not None and str(claimed).strip().lower() not in owners:
        raise WireError("user_mismatch: this fix belongs to another user (flush the queue before signing out)")
    if not ANDROID_MARKERS & raw.keys():
        out = {k: v for k, v in raw.items() if k not in _OWNER_KEYS}
        if "network_type" in out:
            out["network_type"] = _network(out["network_type"])
        return out

    out: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in raw.items():
        if key in _OWNER_KEYS or key in DROPPED or key in ("capture_reason", "geofence_event", "bearing",
                                                            "elapsed_realtime_ns"):
            continue
        if key in RENAMES:
            out[RENAMES[key]] = value
        elif key in PASSTHROUGH:
            out[key] = value
        else:
            unknown.append(key)
    if unknown:
        raise WireError(f"unknown fields: {', '.join(sorted(unknown))} (send PingDto in snake_case, not the "
                        f"local queue entity)")
    if "client_timestamp" in out:
        out["client_timestamp"] = _timestamp(out["client_timestamp"])
    if raw.get("bearing") is not None:
        bearing = float(raw["bearing"])
        out["heading_deg"] = 0.0 if bearing >= 360 else bearing
    if raw.get("elapsed_realtime_ns") is not None:
        out["elapsed_realtime_ms"] = int(raw["elapsed_realtime_ns"]) // 1_000_000
    if "network_type" in out:
        out["network_type"] = _network(out["network_type"])

    reason = raw.get("capture_reason") or "interval"
    if reason not in CAPTURE_REASONS:
        raise WireError(f"unknown capture_reason {reason!r} (allowed: {', '.join(CAPTURE_REASONS)})")
    kind, label = CAPTURE_REASONS[reason]
    out["kind"] = kind
    if label is not None:
        out["checkpoint_label"] = label
    event = raw.get("geofence_event")
    if label in (CheckpointLabel.GEOFENCE_ENTER.value, CheckpointLabel.GEOFENCE_EXIT.value):
        if not isinstance(event, dict) or not event.get("geofence_id"):
            raise WireError(f"capture_reason {reason} needs geofence_event.geofence_id")
        if event.get("type") and f"geofence_{event['type']}" != reason:
            raise WireError(f"geofence_event.type {event['type']!r} contradicts capture_reason {reason!r}")
        out["geofence_uuid"] = event["geofence_id"]
    elif event not in (None, {}):
        raise WireError("geofence_event is only for capture_reason geofence_enter / geofence_exit")
    return out


__all__ = ["CAPTURE_REASONS", "DROPPED", "RENAMES", "WireError", "normalize", "owner_ids"]
