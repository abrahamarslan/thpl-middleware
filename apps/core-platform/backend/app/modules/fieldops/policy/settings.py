"""The settings registry — every policy setting, declared once (docs/fieldops/field-app-integration-plan.md §4.3).

A **setting** is the unit a policy layer sets: a key (``tracking.intervals``), a value model, a
default, and metadata the engine needs:

``binding``    FROZEN — snapshotted onto a shift at start (obligations: a running shift is judged by
               the rules it started under); LIVE — re-resolved on every config refresh (client tuning).
               LOGIN — resolved when a session is created (no shift, no work context).
``audience``   SERVER (enforced here), CLIENT (only rendered to the app), BOTH.
``scopes``     where a layer may set it. A beat-level session rule could never apply (login has no
               shift), so the registry refuses to store one instead of letting it silently do nothing.

Group settings are Pydantic models whose FIELD NAMES are the flat names ``EffectivePolicy`` exposes
(``policy.max_shift_hours``): they are unique across the registry (asserted at import), so the
resolved policy is one flat dict and every pre-layer call site keeps working unchanged. A layer
stores a group PARTIALLY (only the fields it sets); fields merge one by one across layers, and the
merged group is re-validated (cross-field invariants) — a contribution that would break an invariant
is skipped and reported, never applied.

Scalar settings carry one flat name (``consent.required`` → ``require_location_consent``).

Adding a setting = one entry in ``SETTINGS`` — no migration, no new column.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model, model_validator

from app.modules.fieldops.enums import Enforcement, PauseType, TrackingMode


class Binding(str, enum.Enum):
    FROZEN = "frozen"
    LIVE = "live"
    LOGIN = "login"


class Audience(str, enum.Enum):
    SERVER = "server"
    CLIENT = "client"
    BOTH = "both"


class Scope(str, enum.Enum):
    """Targets a layer can have — the dimensions of ``dimensions.py``. Order = precedence rank."""

    ORGANIZATION = "organization"
    ROLE = "role"
    TEAM = "team"
    HUB = "hub"
    BEAT = "beat"
    USER = "user"


ALL_SCOPES = frozenset(Scope)
#: Settings resolved without work context (login) may not be set where only a shift says what applies.
IDENTITY_SCOPES = frozenset({Scope.ORGANIZATION, Scope.ROLE, Scope.USER})


class MockLocationAction(str, enum.Enum):
    FLAG_ONLY = "flag_only"
    REJECT_AND_ALERT = "reject_and_alert"
    END_SHIFT = "end_shift"


class NewLoginAction(str, enum.Enum):
    REVOKE_PREVIOUS = "revoke_previous"
    REFUSE = "refuse"


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── group models ────────────────────────────────────────────────────────────────

class ShiftRequirements(_Group):
    requires_shift: bool = True
    allow_visits_without_shift: bool = False
    require_start_selfie: bool = False
    require_odometer: bool = False
    allow_unscheduled_shifts: bool = Field(True, description="Start with no scheduled shift and no template")


class ShiftWindow(_Group):
    earliest_start_local: dt.time | None = None
    latest_end_local: dt.time | None = None
    start_early_minutes: int = Field(60, ge=0, le=720, description="Earlier than this before planned start = early_start")
    late_start_grace_minutes: int = Field(15, ge=0, le=720)
    max_shift_hours: float = Field(12.0, gt=0, le=24)
    overtime_minutes: int = Field(0, ge=0, le=720, description="Allowed past planned end before the grace starts")
    auto_close_grace_minutes: int = Field(60, ge=0, le=1440)
    stale_shift_after_minutes: int = Field(240, gt=0)
    pre_end_reminder_minutes: int = Field(30, ge=0, le=240)


class PauseRules(_Group):
    max_pause_minutes: int = Field(90, gt=0)
    max_pauses_per_shift: int = Field(6, gt=0)
    paid_pause_types: list[PauseType] = Field(default_factory=lambda: [PauseType.REST, PauseType.MEETING,
                                                                       PauseType.TRAINING])
    track_during_pause: bool = False
    pause_extends_cap: bool = Field(False, description="Pause time pushes the auto-close cap out")


class BatteryBand(_Group):
    min_pct: int = Field(..., ge=0, le=100)
    interval_seconds: int | None = Field(None, gt=0, description="NULL = the base interval")


ActivityKey = Literal["in_vehicle", "walking", "running", "on_bicycle", "still", "unknown"]


class TrackingIntervals(_Group):
    priority: Literal["high_accuracy", "balanced_power_accuracy", "low_power", "passive"] = "balanced_power_accuracy"
    min_interval_s: int = Field(15, gt=0)
    ping_interval_s: int = Field(60, gt=0, description="Base interval")
    max_interval_s: int = Field(600, gt=0)
    stationary_interval_s: int = Field(300, gt=0)
    min_update_interval_ratio: float = Field(0.5, gt=0, le=1)
    max_update_delay_ratio: float = Field(3.0, ge=1, le=10)
    ping_min_distance_m: int = Field(50, ge=0, le=5000)
    battery_bands: list[BatteryBand] = Field(default_factory=lambda: [
        BatteryBand(min_pct=30), BatteryBand(min_pct=15, interval_seconds=120),
        BatteryBand(min_pct=0, interval_seconds=600)])
    activity_intervals: dict[ActivityKey, int | None] = Field(default_factory=lambda: {
        "in_vehicle": 30, "walking": 45, "on_bicycle": 45, "still": None, "unknown": None})

    @model_validator(mode="after")
    def _consistent(self) -> TrackingIntervals:
        lo, hi = self.min_interval_s, self.max_interval_s
        if not lo <= self.ping_interval_s <= hi:
            raise ValueError(f"ping_interval_s must be within [min_interval_s, max_interval_s] = [{lo}, {hi}]")
        if not lo <= self.stationary_interval_s <= hi:
            raise ValueError("stationary_interval_s must be within [min_interval_s, max_interval_s]")
        pcts = [b.min_pct for b in self.battery_bands]
        if not pcts or pcts != sorted(pcts, reverse=True) or len(set(pcts)) != len(pcts) or pcts[-1] != 0:
            raise ValueError("battery_bands: min_pct strictly descending and ending at 0")
        for band in self.battery_bands:
            if band.interval_seconds is not None and not lo <= band.interval_seconds <= hi:
                raise ValueError(f"battery band {band.min_pct}%: interval must be within [{lo}, {hi}]")
        for key, seconds in self.activity_intervals.items():
            if seconds is not None and not lo <= seconds <= hi:
                raise ValueError(f"activity_intervals.{key} must be within [{lo}, {hi}]")
        return self


class TrackingAccuracy(_Group):
    client_max_accuracy_m: int = Field(200, gt=0, description="The app drops fixes worse than this")
    max_fix_accuracy_m: int = Field(100, gt=0, description="Fixes worse than this are never evidence (server)")


class StopCapture(_Group):
    stop_capture_priority: Literal["high_accuracy", "balanced_power_accuracy"] = "high_accuracy"
    stop_capture_timeout_s: int = Field(15, ge=5, le=60)
    stop_capture_fallback_to_last_known: bool = True


class SyncBatch(_Group):
    batch_max_size: int = Field(200, ge=1, le=500)
    batch_max_wait_s: int = Field(60, ge=5, le=3600)
    batch_flush_on_significant: bool = True


class GeofenceRules(_Group):
    geofencing_enabled: bool = True
    geofence_enforcement: Enforcement = Enforcement.ADVISORY
    default_visit_radius_m: int = Field(100, gt=0, le=5000)
    geocoded_radius_factor: float = Field(2.5, ge=1, le=10)
    allow_manual_location: bool = True


class AnomalyThresholds(_Group):
    min_visit_minutes: float = Field(2.0, ge=0)
    late_task_window_hours: int = Field(12, ge=0)
    gap_flag_minutes: int = Field(30, gt=0)
    clock_skew_flag_seconds: int = Field(300, gt=0)
    min_tracking_coverage_pct: float = Field(70.0, ge=0, le=100)


class SecurityIntegrity(_Group):
    mock_location_detection: bool = True
    play_integrity_check: bool = False


class Features(_Group):
    activity_recognition: bool = True
    dashboard_push_enabled: bool = True


class FieldSession(_Group):
    field_max_sessions: int = Field(0, ge=0, le=10, description="Active field-app sessions per user; 0 = unlimited")
    field_on_new_login: NewLoginAction = NewLoginAction.REVOKE_PREVIOUS
    field_drain_grant_hours: int = Field(24, ge=0, le=72,
                                         description="A displaced device may still upload its queued fixes")


# ── the registry ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SettingSpec:
    key: str
    binding: Binding
    audience: Audience
    scopes: frozenset[Scope] = ALL_SCOPES
    model: type[_Group] | None = None          # a group …
    flat: str | None = None                    # … or a scalar with its flat name
    scalar_type: Any = None
    scalar_default: Any = None
    description: str = ""
    lockable: bool = True
    _adapter: Any = field(default=None, repr=False, compare=False)

    @property
    def is_group(self) -> bool:
        return self.model is not None

    def default(self) -> Any:
        return self.model().model_dump(mode="python") if self.is_group else self.scalar_default

    def fields(self) -> tuple[str, ...]:
        return tuple(self.model.model_fields) if self.is_group else (self.flat,)


def _scalar(key, flat, type_, default, binding, audience, scopes=ALL_SCOPES, description=""):
    return SettingSpec(key=key, binding=binding, audience=audience, scopes=scopes, flat=flat, scalar_type=type_,
                       scalar_default=default, description=description,
                       _adapter=TypeAdapter(type_))


def _group(key, model, binding, audience, scopes=ALL_SCOPES, description=""):
    return SettingSpec(key=key, binding=binding, audience=audience, scopes=scopes, model=model,
                       description=description)


_F, _L, _G = Binding.FROZEN, Binding.LIVE, Binding.LOGIN
_S, _C, _B = Audience.SERVER, Audience.CLIENT, Audience.BOTH
_WORK = frozenset({Scope.ORGANIZATION, Scope.ROLE, Scope.TEAM, Scope.HUB, Scope.BEAT})

SETTINGS: dict[str, SettingSpec] = {s.key: s for s in (
    _group("shift.requirements", ShiftRequirements, _F, _S, description="What a shift needs before it starts"),
    _group("shift.window", ShiftWindow, _F, _B, description="Start window, caps and auto-close"),
    _scalar("shift.template", "shift_template", str | None, None, _F, _B,
            description="Code of the shift template used when no shift was scheduled (null = none)"),
    _scalar("shift.start_place", "require_start_at_place_id", int | None, None, _F, _S, _WORK,
            description="Fallback start place (advisory) for shifts with no planned start endpoint"),
    _group("pause.rules", PauseRules, _F, _B, description="Pauses, paid types, tracking while paused"),
    _scalar("consent.required", "require_location_consent", bool, True, _F, _S, IDENTITY_SCOPES,
            description="DPDP: an active location_tracking consent before a shift starts"),
    _scalar("tracking.mode", "tracking_mode", TrackingMode, TrackingMode.CONTINUOUS, _L, _B),
    _group("tracking.intervals", TrackingIntervals, _L, _B, description="The adaptive interval curve"),
    _group("tracking.accuracy", TrackingAccuracy, _L, _B),
    _scalar("tracking.silence", "silence_factor", float, 3.0, _L, _S,
            description="An open shift silent for factor × max interval raises tracking_silent"),
    _group("stop_capture", StopCapture, _L, _C, description="The one-shot proof-of-stop fix"),
    _group("sync.batch", SyncBatch, _L, _C),
    _scalar("retention.local", "local_synced_data_days", int, 5, _L, _C,
            frozenset({Scope.ORGANIZATION, Scope.ROLE})),
    _group("geofence.rules", GeofenceRules, _F, _B),
    _group("anomaly.thresholds", AnomalyThresholds, _F, _S, _WORK),
    _scalar("security.mock_location_action", "mock_location_action", MockLocationAction,
            MockLocationAction.FLAG_ONLY, _F, _B, IDENTITY_SCOPES),
    _group("security.integrity", SecurityIntegrity, _L, _C, frozenset({Scope.ORGANIZATION, Scope.ROLE})),
    _group("features", Features, _L, _C),
    _group("session.field", FieldSession, _G, _S, IDENTITY_SCOPES,
           description="Single-session rule for the field app"),
)}

#: flat name → setting key. Unique by construction (asserted below).
FLAT_TO_KEY: dict[str, str] = {}
for _spec in SETTINGS.values():
    for _name in _spec.fields():
        if _name in FLAT_TO_KEY:
            raise RuntimeError(f"policy setting field {_name!r} is declared twice")
        FLAT_TO_KEY[_name] = _spec.key


def defaults() -> dict[str, Any]:
    """{setting key: default value} — the code floor under every resolution."""
    return {key: spec.default() for key, spec in SETTINGS.items()}


_PARTIALS: dict[str, type[BaseModel]] = {}


def _partial(spec: SettingSpec) -> type[BaseModel]:
    """The group with every field optional and no cross-field validator — for a layer's sparse value."""
    if spec.key not in _PARTIALS:
        fields = {name: (info.annotation | None, None) for name, info in spec.model.model_fields.items()}
        _PARTIALS[spec.key] = create_model(f"Partial{spec.model.__name__}",
                                           __config__=ConfigDict(extra="forbid"), **fields)
    return _PARTIALS[spec.key]


class SettingError(ValueError):
    def __init__(self, key: str, msg: str):
        self.key = key
        super().__init__(f"{key}: {msg}")


def validate_layer_value(key: str, value: Any) -> Any:
    """Validate one setting of a layer: unknown keys and wrong types fail; returns the JSON-safe value
    to store (a group → only the fields given)."""
    spec = SETTINGS.get(key)
    if spec is None:
        raise SettingError(key, "unknown setting (GET /api/fieldops/policy-settings lists them)")
    try:
        if spec.is_group:
            if not isinstance(value, dict):
                raise SettingError(key, "a group setting takes an object of fields")
            parsed = _partial(spec).model_validate(value)
            return parsed.model_dump(mode="json", exclude_unset=True)
        return spec._adapter.dump_python(spec._adapter.validate_python(value), mode="json")
    except ValidationError as exc:
        raise SettingError(key, "; ".join(f"{'.'.join(map(str, e['loc'])) or 'value'}: {e['msg']}"
                                          for e in exc.errors())) from None


def merge_group(spec: SettingSpec, current: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """``current`` (python values) ⊕ ``partial`` (stored JSON) → validated python values, or raise."""
    merged = {**spec.model.model_validate(current).model_dump(mode="json"), **partial}
    return spec.model.model_validate(merged).model_dump(mode="python")


def parse_scalar(spec: SettingSpec, value: Any) -> Any:
    return spec._adapter.validate_python(value)


def catalogue() -> list[dict[str, Any]]:
    """The admin catalogue: one entry per setting with its JSON schema and default."""
    out = []
    for spec in SETTINGS.values():
        schema = spec.model.model_json_schema() if spec.is_group else spec._adapter.json_schema()
        default = spec.model().model_dump(mode="json") if spec.is_group else \
            spec._adapter.dump_python(spec.scalar_default, mode="json")
        out.append({"key": spec.key, "kind": "group" if spec.is_group else "scalar", "fields": list(spec.fields()),
                    "binding": spec.binding.value, "audience": spec.audience.value,
                    "scopes": sorted(s.value for s in spec.scopes), "lockable": spec.lockable,
                    "description": spec.description, "default": default, "schema": schema})
    return out


__all__ = [
    "ALL_SCOPES", "FLAT_TO_KEY", "IDENTITY_SCOPES", "SETTINGS", "Audience", "Binding", "MockLocationAction",
    "NewLoginAction", "Scope", "SettingError", "SettingSpec", "catalogue", "defaults", "merge_group", "parse_scalar",
    "validate_layer_value",
]
