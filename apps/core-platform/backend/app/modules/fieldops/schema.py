"""Transport schemas for field operations.

Conventions
-----------
* Public ids are ``uuid``s. Entities created by the field app carry the CLIENT's UUIDv7 as
  their ``uuid`` — a replayed create finds the same row.
* Every device-originated action carries its clocks (``occurred``: the wall clock as
  ``client_timestamp`` + the monotonic ``elapsed_realtime_ms`` / ``boot_count``); the
  send-time clocks come from headers (``deps.device_clock``). ``clock.py`` turns them into
  ``occurred_at``.
* Coordinates: latitude first on the wire, validated here once (NaN / infinity refused —
  ``nan < -90`` is False, so a range check alone lets it through).
* Lists return ``*Slim`` DTOs, details return the full ``*Out``.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.fieldops.endpoints import EndpointIn, EndpointOut
from app.modules.fieldops.policy.settings import Scope
from app.modules.fieldops.enums import (
    ActivityType,
    AppState,
    BatteryState,
    Channel,
    CheckpointLabel,
    JustificationCode,
    LocationPermission,
    LocationProvider,
    NoOrderReason,
    ParticipantRole,
    PauseType,
    Platform,
    ShiftWorkType,
    TaskType,
    TravelMode,
    VisitCancellationReason,
    VisitOutcome,
    VisitPurpose,
    VisitSource,
)

_MAX_PINGS = 500


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── device-side building blocks ─────────────────────────────────────────────────

class ClockIn(_In):
    """The device's clocks at the moment of an action."""

    client_timestamp: dt.datetime | None = Field(None, description="Device wall clock (ISO-8601 with offset)")
    elapsed_realtime_ms: int | None = Field(None, ge=0, description="Monotonic clock (Android elapsedRealtime)")
    boot_count: int | None = Field(None, ge=0)

    utc_times = field_validator("client_timestamp", mode="after")(lambda cls, v: _utc(v))


class FixIn(_In):
    """One position fix as the OS reported it. ``uuid`` is the client's id of the fix."""

    uuid: uuid_lib.UUID
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float | None = Field(None, ge=0, allow_inf_nan=False)
    altitude_m: float | None = Field(None, allow_inf_nan=False)
    vertical_accuracy_m: float | None = Field(None, ge=0, allow_inf_nan=False)
    heading_deg: float | None = Field(None, ge=0, lt=360, allow_inf_nan=False)
    heading_accuracy_deg: float | None = Field(None, ge=0, allow_inf_nan=False)
    speed_mps: float | None = Field(None, ge=0, allow_inf_nan=False)
    speed_accuracy_mps: float | None = Field(None, ge=0, allow_inf_nan=False)
    provider: LocationProvider = LocationProvider.FUSED
    satellites: int | None = Field(None, ge=0, le=200)
    is_mock: bool = False
    activity_type: ActivityType | None = None
    activity_confidence: int | None = Field(None, ge=0, le=100)
    battery_pct: int | None = Field(None, ge=0, le=100)
    is_charging: bool | None = None
    power_save: bool | None = None
    network_type: str | None = Field(None, max_length=10)
    battery_state: BatteryState | None = None
    app_state: AppState | None = Field(None, description="foreground | background when the fix was taken")
    sequence_no: int | None = Field(None, ge=0)
    client_timestamp: dt.datetime | None = Field(None, description="Fix time (Location.getTime)")
    elapsed_realtime_ms: int | None = Field(None, ge=0, description="Location.getElapsedRealtimeNanos / 1e6")
    boot_count: int | None = Field(None, ge=0)
    extras: dict[str, Any] | None = None

    utc_times = field_validator("client_timestamp", mode="after")(lambda cls, v: _utc(v))


class PingIn(FixIn):
    """One item of a batch upload. Validated ONE BY ONE by the ingest (a bad item is rejected, not the batch)."""

    kind: str = Field("continuous", pattern="^(continuous|checkpoint|manual)$")
    checkpoint_label: str | None = None
    shift_uuid: uuid_lib.UUID | None = None
    visit_uuid: uuid_lib.UUID | None = Field(None, description="The visit / stop (Android stop_id)")
    geofence_uuid: uuid_lib.UUID | None = Field(None, description="fence_id from the fence pack (enter/exit)")
    client_significant: bool | None = Field(None, description="Client hint; the server decides")
    client_distance_m: float | None = Field(None, ge=0, allow_inf_nan=False, description="Client hint")
    manual_reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _consistent(self) -> PingIn:
        if self.provider is LocationProvider.MANUAL and not self.manual_reason:
            raise ValueError("a manual fix needs manual_reason")
        geofence = self.checkpoint_label in (CheckpointLabel.GEOFENCE_ENTER.value, CheckpointLabel.GEOFENCE_EXIT.value)
        if geofence and self.geofence_uuid is None:
            raise ValueError("a geofence_enter / geofence_exit checkpoint needs geofence_uuid")
        if self.geofence_uuid is not None and not geofence:
            raise ValueError("geofence_uuid is only for geofence_enter / geofence_exit checkpoints")
        if self.checkpoint_label is not None:
            if self.kind != "checkpoint":
                raise ValueError("checkpoint_label requires kind='checkpoint'")
            if self.checkpoint_label not in {label.value for label in CheckpointLabel}:
                raise ValueError(f"unknown checkpoint_label {self.checkpoint_label!r}")
        return self


class PingBatchIn(_In):
    uuid: uuid_lib.UUID = Field(..., description="Client batch id — a re-sent batch is answered from the ledger")
    pings: list[dict[str, Any]] = Field(..., min_length=1, max_length=_MAX_PINGS)


class ManualLocationIn(_In):
    """No usable GPS (indoors, a steel-shuttered shop): record why. Never evidence of presence."""

    reason: str = Field(..., min_length=3, max_length=500)
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)


class _Located(_In):
    occurred: ClockIn = Field(default_factory=ClockIn)
    fix: FixIn | None = None
    manual_location: ManualLocationIn | None = None


# ── devices ─────────────────────────────────────────────────────────────────────

class SessionIn(_In):
    uuid: uuid_lib.UUID = Field(..., description="Client session id (one per app launch)")
    client_app_version: str | None = Field(None, max_length=32)
    client_build: str | None = Field(None, max_length=32)
    os_version: str | None = Field(None, max_length=40)
    sdk_int: int | None = Field(None, ge=0)
    boot_count: int | None = Field(None, ge=0)
    location_permission: LocationPermission | None = None
    precise_location: bool | None = None
    battery_optimization_exempt: bool | None = None
    power_save_mode: bool | None = None
    auto_time_enabled: bool | None = None
    auto_timezone_enabled: bool | None = None
    developer_options: bool | None = None
    is_rooted: bool | None = None
    integrity_verdict: str | None = Field(None, max_length=40)
    network_type: str | None = Field(None, max_length=10)
    carrier: str | None = Field(None, max_length=60)
    locale: str | None = Field(None, max_length=20)
    device_timezone: str | None = Field(None, max_length=64)


class DeviceRegisterIn(_In):
    installation_id: str = Field(..., min_length=8, max_length=64)
    platform: Platform
    manufacturer: str | None = Field(None, max_length=100)
    model: str | None = Field(None, max_length=100)
    os_version: str | None = Field(None, max_length=40)
    app_id: str | None = Field(None, max_length=100)
    push_token: str | None = Field(None, max_length=4096)
    session: SessionIn


class DeviceEventIn(_In):
    uuid: uuid_lib.UUID
    event_type: str = Field(..., max_length=40)
    client_timestamp: dt.datetime | None = None
    elapsed_realtime_ms: int | None = Field(None, ge=0)
    boot_count: int | None = Field(None, ge=0)
    details: dict[str, Any] | None = None

    utc_times = field_validator("client_timestamp", mode="after")(lambda cls, v: _utc(v))


class DeviceEventsIn(_In):
    events: list[DeviceEventIn] = Field(..., min_length=1, max_length=500)


class DeviceOut(_Out):
    uuid: uuid_lib.UUID
    installation_id: str
    platform: str
    manufacturer: str | None
    model: str | None
    is_primary: bool
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime


class DeviceSessionOut(_Out):
    uuid: uuid_lib.UUID
    started_at: dt.datetime
    client_app_version: str | None
    location_permission: str | None
    precise_location: bool | None


class DeviceRegisteredOut(BaseModel):
    device: DeviceOut
    session: DeviceSessionOut
    warnings: list[str] = Field(default_factory=list,
                                description="Capability problems that will break tracking (permission, battery)")


class DeviceEventsResultOut(BaseModel):
    accepted: int
    duplicates: int


# ── shifts ──────────────────────────────────────────────────────────────────────

class JustificationIn(_In):
    code: JustificationCode
    note: str | None = Field(None, max_length=1000)



class ShiftStartIn(_Located):
    """Start a shift. ``uuid`` = a SCHEDULED shift's uuid (from ``GET /me/shifts``) starts that shift;
    a new uuid starts from the user's shift template (or ad hoc, when the policy allows)."""

    uuid: uuid_lib.UUID = Field(..., description="Client-generated UUIDv7, or the scheduled shift's uuid")
    justification: JustificationIn | None = Field(None, description="Why you are outside the start location "
                                                                    "(soft_block)")
    planned_end_at: dt.datetime | None = None
    vehicle_id: int | None = Field(None, gt=0)
    travel_mode: TravelMode | None = None
    odometer_start_km: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=1)
    selfie_media_uuid: uuid_lib.UUID | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("planned_end_at", mode="after")(lambda cls, v: _utc(v))


class ShiftEndIn(_Located):
    odometer_end_km: Decimal | None = Field(None, ge=0, max_digits=10, decimal_places=1)
    notes: str | None = Field(None, max_length=2000)


class ShiftPauseIn(_Located):
    uuid: uuid_lib.UUID = Field(..., description="Client-generated UUIDv7 — the pause's id")
    pause_type: PauseType
    reason: str | None = Field(None, max_length=500)


class ShiftResumeIn(_Located):
    pass


class PauseOut(_Out):
    uuid: uuid_lib.UUID
    pause_type: str
    reason: str | None
    is_paid: bool
    tracking_suspended: bool
    started_at: dt.datetime
    start_time_basis: str
    ended_at: dt.datetime | None
    end_reason: str | None
    ended_by: str | None


class HubRef(BaseModel):
    id: int
    code: str | None = None
    name: str | None = None


class TemplateRef(BaseModel):
    uuid: uuid_lib.UUID | None = None
    code: str
    name: str


class ShiftSlim(_Out):
    """A shift as lists show it — the plan (title, work type, window, where it starts and ends, the hub),
    the outcome (status, times, checks) and the stop counts. ``uuid`` is null only for a VIRTUAL entry
    (``source = template``, a template occurrence nobody has started yet): start it with a new uuid."""

    uuid: uuid_lib.UUID | None
    shift_code: str | None = None
    title: str | None = None
    work_type: str | None = None
    source: str = "ad_hoc"
    user_id: int
    shift_date: dt.date
    status: str
    review_status: str
    planned_start_at: dt.datetime | None = None
    planned_end_at: dt.datetime | None = None
    auto_close_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    paused_since: dt.datetime | None = None
    pause_count: int = 0
    wall_clock_minutes: float | None = None
    paid_minutes: float | None = None
    duration_basis: str | None = None
    start_check: str = "not_configured"
    start_distance_m: float | None = None
    end_check: str = "not_configured"
    end_distance_m: float | None = None
    hub: HubRef | None = None
    template: TemplateRef | None = None
    start_location: EndpointOut | None = None
    end_location: EndpointOut | None = None
    stops_total: int = 0
    stops_completed: int = 0


class CapturedPoint(BaseModel):
    """A checkpoint fix the app sent with an action (the shift's actual start / end location)."""

    latitude: float
    longitude: float
    accuracy_m: float | None
    recorded_at: dt.datetime
    occurred_at: dt.datetime
    is_mock: bool


class ShiftOut(ShiftSlim):
    organization_id: int
    device_id: int | None
    policy_id: int | None
    policy_snapshot: dict
    start_received_at: dt.datetime | None
    start_time_basis: str | None
    start_client_timestamp: dt.datetime | None
    start_manual_location_reason: str | None
    start_selfie_media_uuid: uuid_lib.UUID | None
    end_received_at: dt.datetime | None
    end_time_basis: str | None
    end_client_timestamp: dt.datetime | None
    ended_by: str | None
    end_reason: str | None
    pause_minutes: float | None
    unpaid_pause_minutes: float | None
    last_activity_at: dt.datetime | None
    vehicle_id: int | None
    travel_mode: str | None
    odometer_start_km: float | None
    odometer_end_km: float | None
    cancellation_reason: str | None
    notes: str | None
    assigned_by: int | None = None
    reviewed_by: int | None
    reviewed_at: dt.datetime | None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime
    captured_start: CapturedPoint | None = None
    captured_end: CapturedPoint | None = None


class ShiftScheduleIn(_In):
    """Schedule a shift for a user. Either an explicit window (``planned_start_at`` + ``planned_end_at``) or a
    ``template`` (code/uuid) and an optional ``date`` (default today, in the template's timezone); explicit
    fields override the template's. ``start``/``end`` omitted = the template's, else anywhere."""

    uuid: uuid_lib.UUID | None = Field(None, description="Optional client id — a replay returns the same shift")
    user_id: int = Field(..., gt=0)
    template: str | None = Field(None, max_length=64, description="Template code or uuid")
    date: dt.date | None = Field(None, description="Business date of the template occurrence")
    planned_start_at: dt.datetime | None = None
    planned_end_at: dt.datetime | None = None
    title: str | None = Field(None, max_length=200)
    work_type: ShiftWorkType | None = None
    start: EndpointIn | None = None
    end: EndpointIn | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("planned_start_at", "planned_end_at", mode="after")(lambda cls, v: _utc(v))


class ShiftScheduleBulkIn(_In):
    shifts: list[ShiftScheduleIn] = Field(..., min_length=1, max_length=200)


class ShiftScheduleUpdate(_In):
    row_version: int = Field(..., ge=1)
    planned_start_at: dt.datetime | None = None
    planned_end_at: dt.datetime | None = None
    title: str | None = Field(None, max_length=200)
    work_type: ShiftWorkType | None = None
    start: EndpointIn | None = None
    end: EndpointIn | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("planned_start_at", "planned_end_at", mode="after")(lambda cls, v: _utc(v))


class ShiftHandoverIn(_In):
    occurred: ClockIn = Field(default_factory=ClockIn)


# ── shift templates ─────────────────────────────────────────────────────────────

class ShiftTemplateIn(_In):
    code: str = Field(..., min_length=2, max_length=40, pattern="^[A-Za-z0-9_\\-]+$")
    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    title_pattern: str | None = Field(None, max_length=200)
    work_type: ShiftWorkType = ShiftWorkType.OTHER
    start_local_time: dt.time
    end_local_time: dt.time
    end_day_offset: int = Field(0, ge=0, le=1)
    timezone: str | None = Field(None, max_length=64, description="IANA zone; omitted = the organization's")
    days_of_week: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    valid_from: dt.date | None = None
    valid_until: dt.date | None = None
    status: str = Field("active", pattern="^(active|inactive)$")
    start: EndpointIn | None = None
    end: EndpointIn | None = None

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, value: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in value):
            raise ValueError("days_of_week are ISO weekdays 1 (Monday) … 7 (Sunday)")
        return value

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception:  # noqa: BLE001
            raise ValueError(f"unknown timezone {value!r}") from None
        return value


class ShiftTemplateUpdate(_In):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    title_pattern: str | None = Field(None, max_length=200)
    work_type: ShiftWorkType | None = None
    start_local_time: dt.time | None = None
    end_local_time: dt.time | None = None
    end_day_offset: int | None = Field(None, ge=0, le=1)
    timezone: str | None = Field(None, max_length=64)
    days_of_week: list[int] | None = Field(None, min_length=1, max_length=7)
    valid_from: dt.date | None = None
    valid_until: dt.date | None = None
    status: str | None = Field(None, pattern="^(active|inactive)$")
    start: EndpointIn | None = None
    end: EndpointIn | None = None


class ShiftTemplateOut(_Out):
    uuid: uuid_lib.UUID
    id: int
    organization_id: int
    code: str
    name: str
    description: str | None
    title_pattern: str | None
    work_type: str
    start_local_time: dt.time
    end_local_time: dt.time
    end_day_offset: int
    timezone: str | None
    days_of_week: list[int]
    valid_from: dt.date | None
    valid_until: dt.date | None
    status: str
    start_location: EndpointOut | None = None
    end_location: EndpointOut | None = None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime


# ── stops (planned visits) ──────────────────────────────────────────────────────

class StopIn(_In):
    """One stop of a shift = a PLANNED visit. Where: ``place_uuid``, or ``latitude``/``longitude`` (+ address),
    or an account whose address book has a place."""

    uuid: uuid_lib.UUID | None = None
    sequence: int | None = Field(None, ge=0)
    purpose: str = Field("delivery", max_length=20)
    account: dict[str, Any] | None = Field(None, description='{"type": "customer", "id": 42}')
    place_uuid: uuid_lib.UUID | None = None
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    address: str | None = Field(None, max_length=500)
    name: str | None = Field(None, max_length=255)
    planned_start_at: dt.datetime | None = None
    planned_end_at: dt.datetime | None = None
    stop_code: str | None = Field(None, max_length=40)
    external_ref: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("planned_start_at", "planned_end_at", mode="after")(lambda cls, v: _utc(v))


class StopsIn(_In):
    stops: list[StopIn] = Field(..., min_length=1, max_length=200)


class FenceOut(BaseModel):
    """One circle for Android's GeofencingClient (``requestId`` = ``fence_id``). A polygon fence is sent as
    its minimum enclosing circle; the SERVER still verifies against the polygon."""

    fence_id: uuid_lib.UUID
    kind: str                      # start | end | stop
    place_uuid: uuid_lib.UUID | None
    visit_uuid: uuid_lib.UUID | None = None
    latitude: float
    longitude: float
    radius_m: float
    enforcement: str | None = None


class StopOut(BaseModel):
    uuid: uuid_lib.UUID
    sequence: int | None
    status: str
    purpose: str
    stop_code: str | None
    external_ref: str | None
    account_type: str | None
    account_id: int | None
    planned_start_at: dt.datetime | None
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    start_check: str
    location: EndpointOut | None = None


class MyShiftDetailOut(BaseModel):
    shift: ShiftOut
    stops: list[StopOut]
    fences: list[FenceOut]


class VisitStartPlannedIn(_Located):
    """Start a PLANNED visit (a stop): the fix is the proof-of-presence capture."""

    justification: JustificationIn | None = None
    notes: str | None = Field(None, max_length=2000)


# ── visits ──────────────────────────────────────────────────────────────────────

class AccountRef(_In):
    type: str = Field(..., max_length=64, description="core.entity_types.code, e.g. 'customer'")
    id: int = Field(..., gt=0)


class VisitStartIn(_Located):
    uuid: uuid_lib.UUID = Field(..., description="Client-generated UUIDv7 — the visit's id")
    shift_uuid: uuid_lib.UUID | None = Field(None, description="Defaults to the caller's open shift")
    channel: Channel = Channel.FIELD
    purpose: VisitPurpose = VisitPurpose.SALES_CALL
    source: VisitSource = VisitSource.UNPLANNED
    plan_ref: uuid_lib.UUID | None = None
    sequence_in_plan: int | None = Field(None, ge=0)
    account: AccountRef | None = None
    place_uuid: uuid_lib.UUID | None = None
    planned_start_at: dt.datetime | None = None
    justification: JustificationIn | None = None
    notes: str | None = Field(None, max_length=2000)


class VisitEndIn(_Located):
    outcome: VisitOutcome | None = None
    no_order_reason: NoOrderReason | None = None
    follow_up_at: dt.datetime | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("follow_up_at", mode="after")(lambda cls, v: _utc(v))


class VisitCancelIn(_In):
    occurred: ClockIn = Field(default_factory=ClockIn)
    reason: VisitCancellationReason = VisitCancellationReason.USER
    note: str | None = Field(None, max_length=1000)


class VisitJoinIn(_In):
    occurred: ClockIn = Field(default_factory=ClockIn)
    participant_role: ParticipantRole = ParticipantRole.JOINT_WORKING


class VisitSlim(_Out):
    uuid: uuid_lib.UUID
    user_id: int
    shift_id: int | None
    channel: str
    status: str
    review_status: str
    purpose: str
    account_type: str | None
    account_id: int | None
    place_id: int | None
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    start_check: str
    outcome: str | None


class VisitOut(VisitSlim):
    organization_id: int
    source: str
    plan_ref: uuid_lib.UUID | None
    sequence_in_plan: int | None
    planned_start_at: dt.datetime | None
    start_received_at: dt.datetime | None
    start_time_basis: str | None
    start_client_timestamp: dt.datetime | None
    end_received_at: dt.datetime | None
    end_time_basis: str | None
    end_client_timestamp: dt.datetime | None
    geofence_entry_at: dt.datetime | None
    geofence_exit_at: dt.datetime | None
    visit_time_basis: str | None
    end_check: str
    distance_from_target_m: Decimal | None
    start_justification_code: str | None
    start_justification_note: str | None
    manual_location_reason: str | None
    no_order_reason: str | None
    follow_up_at: dt.datetime | None
    cancellation_reason: str | None
    cancelled_at: dt.datetime | None
    notes: str | None
    reviewed_by: int | None
    reviewed_at: dt.datetime | None
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime


class ParticipantOut(_Out):
    uuid: uuid_lib.UUID
    user_id: int
    participant_role: str
    joined_at: dt.datetime
    left_at: dt.datetime | None


# ── tasks ───────────────────────────────────────────────────────────────────────

class ReferenceIn(_In):
    type: str = Field(..., max_length=64, description="core.entity_types.code of the document")
    id: int | None = Field(None, gt=0)
    uuid: uuid_lib.UUID | None = Field(None, description="Client uuid of a document created offline")

    @model_validator(mode="after")
    def _one_of(self) -> ReferenceIn:
        if self.id is None and self.uuid is None:
            raise ValueError("a reference needs an id or a uuid")
        return self


class TaskIn(_In):
    uuid: uuid_lib.UUID = Field(..., description="Client-generated UUIDv7 — the task's id")
    task_type: TaskType
    occurred: ClockIn = Field(default_factory=ClockIn)
    fix: FixIn | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reference: ReferenceIn | None = None
    amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency_code: str | None = Field(None, pattern="^[A-Z]{3}$")

    @model_validator(mode="after")
    def _amount_currency(self) -> TaskIn:
        if self.amount is not None and self.currency_code is None:
            raise ValueError("an amount needs its currency_code")
        return self


class TaskVoidIn(_In):
    reason: str = Field(..., min_length=3, max_length=500)


class TaskOut(_Out):
    uuid: uuid_lib.UUID
    visit_id: int
    user_id: int
    task_type: str
    status: str
    performed_at: dt.datetime
    received_at: dt.datetime
    time_basis: str
    client_timestamp: dt.datetime | None
    after_visit_end: bool
    payload: dict
    payload_version: int
    reference_type: str | None
    reference_id: int | None
    reference_uuid: uuid_lib.UUID | None
    amount: Decimal | None
    currency_code: str | None
    void_reason: str | None


# ── the stream ──────────────────────────────────────────────────────────────────

class PingItemResult(BaseModel):
    uuid: str | None
    status: str
    reason: str | None = None


class PingBatchResultOut(BaseModel):
    batch_uuid: uuid_lib.UUID
    accepted: int
    duplicates: int
    rejected: int
    results: list[PingItemResult] = Field(default_factory=list,
                                          description="Non-accepted items only; drop accepted + duplicate locally")
    replayed: bool = False


class TrackPoint(BaseModel):
    uuid: uuid_lib.UUID
    occurred_at: dt.datetime
    latitude: float
    longitude: float
    accuracy_m: float | None
    kind: str
    checkpoint_label: str | None
    quality_flags: int


class TrackOut(BaseModel):
    shift_uuid: uuid_lib.UUID
    points: list[TrackPoint]
    geojson: dict


class LocationCheckOut(_Out):
    uuid: uuid_lib.UUID
    phase: str
    evaluated_at: dt.datetime
    at: dt.datetime
    target_kind: str
    geofence_id: int | None
    place_id: int | None
    radius_m: float | None
    distance_m: float | None
    fix_accuracy_m: float | None
    evidence_count: int
    result: str
    enforcement: str
    action_taken: str


# ── current state / policy ──────────────────────────────────────────────────────

class CurrentOut(BaseModel):
    """What the app needs to resume after a restart."""

    shift: ShiftOut | None = None
    open_pause: PauseOut | None = None
    visit: VisitOut | None = None
    consent: dict[str, Any] = Field(default_factory=dict,
                                    description='{"location_tracking": {"given", "version", "required"}} — prompt '
                                                'before starting a shift when required and not given')


class EffectivePolicyOut(BaseModel):
    policy_id: int | None
    policy_uuid: uuid_lib.UUID | None
    values: dict[str, Any]
    can_telephonic: bool
    layers: list[str] = Field(default_factory=list, description="Contributing layer uuids, general → specific")
    epoch: int = 0


class PolicyLayerIn(_In):
    """A policy layer for the request's organization (``X-Organization-Code``): an organization
    fallback (``scope_type = organization``) or a role / team / hub / user target within it."""

    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    scope_type: Scope = Scope.ORGANIZATION
    scope_id: int | None = Field(None, gt=0, description="roles/teams/hubs/users id; omitted for organization")
    settings: dict[str, Any] = Field(default_factory=dict,
                                     description="Sparse {setting key: value}; GET /policy-settings lists the keys")
    locked_keys: list[str] = Field(default_factory=list, description="Keys (or key.field) narrower layers may not override")
    priority: int = Field(0, ge=-100, le=100)
    effective_from: dt.datetime | None = None
    effective_until: dt.datetime | None = None
    status: str = Field("active", pattern="^(active|inactive)$")

    utc_times = field_validator("effective_from", "effective_until", mode="after")(lambda cls, v: _utc(v))


class PolicyLayerUpdate(_In):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = Field(None, max_length=2000)
    settings: dict[str, Any] | None = Field(None, description="Keys to set/replace (others are kept)")
    unset: list[str] | None = Field(None, description="Keys (or key.field) to remove — back to inheritance")
    locked_keys: list[str] | None = None
    priority: int | None = Field(None, ge=-100, le=100)
    effective_from: dt.datetime | None = None
    effective_until: dt.datetime | None = None
    status: str | None = Field(None, pattern="^(active|inactive)$")

    utc_times = field_validator("effective_from", "effective_until", mode="after")(lambda cls, v: _utc(v))


class PolicyPreviewIn(PolicyLayerIn):
    replaces: str | None = Field(None, description="uuid of the layer this draft would replace")


class PolicyLayerOut(_Out):
    uuid: uuid_lib.UUID
    id: int
    organization_id: int
    name: str
    description: str | None
    scope_type: str
    scope_id: int | None
    settings: dict[str, Any]
    locked_keys: list[str]
    priority: int
    effective_from: dt.datetime | None
    effective_until: dt.datetime | None
    status: str
    row_version: int
    created_at: dt.datetime
    updated_at: dt.datetime


class PolicyLayerWriteOut(BaseModel):
    layer: PolicyLayerOut
    warnings: list[dict[str, Any]] = Field(default_factory=list,
                                           description="Contributions that would be skipped (invalid combination)")


# ── manager side ────────────────────────────────────────────────────────────────

class ShiftCorrectIn(_In):
    """A manager's correction. Times are business times (UTC); ``reason`` is mandatory and recorded."""

    row_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=3, max_length=1000)
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("started_at", "ended_at", mode="after")(lambda cls, v: _utc(v))


class VisitCorrectIn(_In):
    row_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=3, max_length=1000)
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None
    outcome: VisitOutcome | None = None
    notes: str | None = Field(None, max_length=2000)

    utc_times = field_validator("started_at", "ended_at", mode="after")(lambda cls, v: _utc(v))


class ReviewIn(_In):
    decision: str = Field(..., pattern="^(approve|reject)$")
    note: str | None = Field(None, max_length=2000)


class AnomalyOut(_Out):
    uuid: uuid_lib.UUID
    anomaly_type: str
    severity: str
    status: str
    subject_type: str
    subject_id: int
    user_id: int | None
    shift_id: int | None
    detected_at: dt.datetime
    detector: str
    evidence: dict
    resolved_by: int | None
    resolved_at: dt.datetime | None
    resolution_code: str | None
    resolution_note: str | None


class AnomalyResolveIn(_In):
    status: str = Field(..., pattern="^(acknowledged|resolved|dismissed)$")
    resolution_code: str | None = Field(None, max_length=40)
    note: str | None = Field(None, max_length=2000)


class MetricsOut(_Out):
    shift_id: int
    computed_at: dt.datetime
    metrics_version: int
    wall_clock_minutes: Decimal | None
    pause_minutes: Decimal | None
    paid_minutes: Decimal | None
    engaged_minutes: Decimal | None
    visit_minutes: Decimal | None
    travel_minutes: Decimal | None
    idle_minutes: Decimal | None
    first_visit_at: dt.datetime | None
    last_visit_at: dt.datetime | None
    fix_count: int
    accepted_fix_count: int
    tracking_coverage_pct: Decimal | None
    longest_gap_minutes: Decimal | None
    mock_fix_count: int
    low_accuracy_fix_count: int
    clock_skew_max_s: int | None
    gps_distance_km: Decimal | None
    odometer_distance_km: Decimal | None
    visits_total: int
    visits_completed: int
    visits_cancelled: int
    visits_planned: int
    visits_unplanned: int
    field_visits: int
    telephonic_visits: int
    video_visits: int
    productive_visits: int
    visits_checked: int
    visits_inside: int
    visits_outside: int
    visits_uncertain: int
    geofence_compliance_pct: Decimal | None
    orders_field: int
    orders_telephonic: int
    order_value_field: Decimal
    order_value_telephonic: Decimal
    collections_value: Decimal
    currency_code: str | None
    anomaly_count_open: int


class ShiftDetailOut(BaseModel):
    shift: ShiftOut
    pauses: list[PauseOut]
    visits: list[VisitSlim]
    metrics: MetricsOut | None
    open_anomalies: list[AnomalyOut]


class VisitDetailOut(BaseModel):
    visit: VisitOut
    tasks: list[TaskOut]
    participants: list[ParticipantOut]
    checks: list[LocationCheckOut]


class LiveUserOut(BaseModel):
    user_id: int
    latitude: float | None
    longitude: float | None
    accuracy_m: float | None
    recorded_at: dt.datetime | None
    shift_uuid: uuid_lib.UUID | None
    shift_status: str | None
    visit_uuid: uuid_lib.UUID | None


class ReviewQueueOut(BaseModel):
    shifts: list[ShiftSlim]
    visits: list[VisitSlim]
    anomalies: list[AnomalyOut]
