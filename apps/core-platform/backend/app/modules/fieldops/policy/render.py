"""Render the field app's configuration JSON from a resolved policy (plan §4.7).

The shape is the Android ``LocationConfig`` contract (v5: battery bands instead of v4's overlapping
above/below thresholds). Only settings whose audience is CLIENT or BOTH reach the app; everything is
derived from the flat policy, so a value cannot be configured in two places.

``frozen`` (the open shift's snapshot, flat) overrides the FROZEN settings: a running shift keeps the
obligations it started under; LIVE tuning (intervals, flush cadence) always comes from ``live``.
"""

from __future__ import annotations

import datetime as dt
import enum
import hashlib
import json
from typing import Any

from app.modules.fieldops.policy.settings import SETTINGS, Binding, MockLocationAction

CONFIG_SCHEMA_VERSION = 5


def _v(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dt.time):
        return value.isoformat()
    if isinstance(value, list):
        return [_v(v) for v in value]
    if isinstance(value, dict):
        return {k: _v(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def effective_flat(live: dict[str, Any], frozen: dict[str, Any] | None) -> dict[str, Any]:
    """``live`` with every FROZEN setting's fields taken from ``frozen`` (when a shift is open)."""
    if not frozen:
        return dict(live)
    out = dict(live)
    for spec in SETTINGS.values():
        if spec.binding is Binding.FROZEN:
            for name in spec.fields():
                if name in frozen:
                    out[name] = frozen[name]
    return out


def render(flat: dict[str, Any], *, config_version: int, effective_from: dt.datetime | None,
           auto_close_at: dt.datetime | None = None, planned_end_at: dt.datetime | None = None) -> dict[str, Any]:
    f = {k: _v(v) for k, v in flat.items()}
    base = int(f["ping_interval_s"])
    activity = dict(f["activity_intervals"] or {})
    if activity.get("still") is None:
        activity["still"] = int(f["stationary_interval_s"])
    action = f["mock_location_action"]
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "config_version": int(config_version),
        "effective_from": effective_from.isoformat() if effective_from else None,
        "location_request": {
            "tracking_mode": f["tracking_mode"],
            "priority": f["priority"],
            "base_interval_seconds": base,
            "min_interval_seconds": int(f["min_interval_s"]),
            "max_interval_seconds": int(f["max_interval_s"]),
            "min_update_interval_ratio": float(f["min_update_interval_ratio"]),
            "max_update_delay_ratio": float(f["max_update_delay_ratio"]),
            "significant_distance_meters": int(f["ping_min_distance_m"]),
            "battery_thresholds": [
                {"min_pct": int(b["min_pct"]),
                 "interval_seconds": int(b["interval_seconds"]) if b.get("interval_seconds") else base}
                for b in f["battery_bands"]
            ],
            "activity_based_intervals": activity,
            "track_during_pause": bool(f["track_during_pause"]),
        },
        "stop_capture": {
            "priority": f["stop_capture_priority"],
            "timeout_seconds": int(f["stop_capture_timeout_s"]),
            "fallback_to_last_known_on_timeout": bool(f["stop_capture_fallback_to_last_known"]),
        },
        "batch_flush": {
            "max_batch_size": int(f["batch_max_size"]),
            "max_wait_seconds": int(f["batch_max_wait_s"]),
            "flush_immediately_on_significant": bool(f["batch_flush_on_significant"]),
        },
        "accuracy_filter": {"max_accepted_accuracy_meters": int(f["client_max_accuracy_m"])},
        "geofencing": {
            "enabled": bool(f["geofencing_enabled"]) and f["tracking_mode"] != "off",
            "default_radius_meters": int(f["default_visit_radius_m"]),
            "enforcement": f["geofence_enforcement"],
        },
        "shift_boundaries": {
            "max_shift_duration_hours": float(f["max_shift_hours"]),
            "pre_end_reminder_minutes": int(f["pre_end_reminder_minutes"]),
            "auto_close_at": auto_close_at.isoformat() if auto_close_at else None,
            "planned_end_at": planned_end_at.isoformat() if planned_end_at else None,
        },
        "retention": {"local_synced_data_days": int(f["local_synced_data_days"])},
        "feature_flags": {
            "mock_location_detection": bool(f["mock_location_detection"]),
            "enforce_mock_rejection": action != MockLocationAction.FLAG_ONLY.value,
            "mock_location_action": action,
            "dashboard_push_enabled": bool(f["dashboard_push_enabled"]),
            "activity_recognition": bool(f["activity_recognition"]),
            "play_integrity_check": bool(f["play_integrity_check"]),
        },
    }


def etag(body: dict[str, Any]) -> str:
    return '"' + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32] + '"'


__all__ = ["CONFIG_SCHEMA_VERSION", "effective_flat", "etag", "render"]
