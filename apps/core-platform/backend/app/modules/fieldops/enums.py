"""Closed vocabularies of the field-operations module.

Every CHECK constraint in ``fieldops`` is generated from these enums through
:func:`values`, so the database and the code cannot disagree about a spelling.
Adding a value = add it here + one CHECK migration (the task-type registry in
``task_types.py`` is the only other place a new ``TaskType`` must be declared).

docs/fieldops/implementation-of-shift-visits-system.md is the reference for
what each value means.
"""

from __future__ import annotations

import enum

FIELDOPS_SCHEMA = "fieldops"


def values(enum_cls: type[enum.Enum]) -> str:
    """``'a', 'b', 'c'`` — for ``CHECK (col IN (...))``."""
    return ", ".join(f"'{member.value}'" for member in enum_cls)


class ShiftStatus(str, enum.Enum):
    """Lifecycle of a work session. ``active`` and ``paused`` are both OPEN:
    at most one open shift per user (``uq_shifts_one_open``)."""

    SCHEDULED = "scheduled"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    AUTO_CLOSED = "auto_closed"
    CANCELLED = "cancelled"


OPEN_SHIFT_STATUSES = (ShiftStatus.ACTIVE.value, ShiftStatus.PAUSED.value)
CLOSED_SHIFT_STATUSES = (ShiftStatus.COMPLETED.value, ShiftStatus.AUTO_CLOSED.value, ShiftStatus.CANCELLED.value)


class VisitStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    MISSED = "missed"


class ReviewStatus(str, enum.Enum):
    """The review axis — orthogonal to the lifecycle (improvement-document F-22)."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class EndedBy(str, enum.Enum):
    USER = "user"
    SYSTEM = "system"
    MANAGER = "manager"


class ShiftEndReason(str, enum.Enum):
    USER = "user"
    AUTO_CLOSED = "auto_closed"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    MANAGER_CORRECTION = "manager_correction"


class DurationBasis(str, enum.Enum):
    DEVICE_REPORTED = "device_reported"
    SYSTEM_ESTIMATED = "system_estimated"
    MANAGER_ADJUSTED = "manager_adjusted"


class TimeBasis(str, enum.Enum):
    """How ``occurred_at`` was derived (clock.py), best evidence first."""

    #: from the device's monotonic clock (same boot) — immune to the user changing the clock
    MONOTONIC = "monotonic"
    #: device wall clock corrected by the skew measured at send (``received_at − sent_at``)
    WALL_CLOCK_CORRECTED = "wall_clock_corrected"
    #: device wall clock as reported, uncorrected (a legacy client sent no send-time headers)
    DEVICE_WALL_CLOCK = "device_wall_clock"
    #: the server's receipt time — no usable device evidence
    SERVER_RECEIPT = "server_receipt"
    #: set by a manager's correction
    MANAGER = "manager"


class PauseType(str, enum.Enum):
    """Why a shift was paused. A break is a pause; whether it is paid is policy
    (``work_policies.paid_pause_types``), not a property of the type."""

    MEAL = "meal"
    REST = "rest"
    PRAYER = "prayer"
    PERSONAL = "personal"
    MEETING = "meeting"
    TRAINING = "training"
    VEHICLE_ISSUE = "vehicle_issue"
    WEATHER = "weather"
    NETWORK_ISSUE = "network_issue"
    OTHER = "other"


class PauseEndReason(str, enum.Enum):
    RESUMED = "resumed"
    SHIFT_ENDED = "shift_ended"
    AUTO_CLOSED = "auto_closed"
    MANAGER = "manager"


class TravelMode(str, enum.Enum):
    TWO_WHEELER = "two_wheeler"
    FOUR_WHEELER = "four_wheeler"
    PUBLIC_TRANSPORT = "public_transport"
    WALK = "walk"
    COMPANY_VEHICLE = "company_vehicle"
    BICYCLE = "bicycle"


class TrackingMode(str, enum.Enum):
    OFF = "off"
    CHECKPOINTS_ONLY = "checkpoints_only"
    CONTINUOUS = "continuous"


class Enforcement(str, enum.Enum):
    ADVISORY = "advisory"
    SOFT_BLOCK = "soft_block"
    HARD_BLOCK = "hard_block"


class Channel(str, enum.Enum):
    FIELD = "field"
    TELEPHONIC = "telephonic"
    VIDEO = "video"


REMOTE_CHANNELS = (Channel.TELEPHONIC.value, Channel.VIDEO.value)


class VisitSource(str, enum.Enum):
    PLANNED = "planned"
    UNPLANNED = "unplanned"


class VisitPurpose(str, enum.Enum):
    SALES_CALL = "sales_call"
    COLLECTION = "collection"
    DELIVERY = "delivery"
    SERVICE = "service"
    MERCHANDISING = "merchandising"
    SURVEY = "survey"
    PROSPECTING = "prospecting"
    RELATIONSHIP = "relationship"


class VisitOutcome(str, enum.Enum):
    ORDER_TAKEN = "order_taken"
    NO_ORDER = "no_order"
    COLLECTION_ONLY = "collection_only"
    DELIVERED = "delivered"
    CLOSED_SHOP = "closed_shop"
    OWNER_ABSENT = "owner_absent"
    FOLLOW_UP = "follow_up"
    INFO_ONLY = "info_only"


class NoOrderReason(str, enum.Enum):
    STOCK_SUFFICIENT = "stock_sufficient"
    PRICE_ISSUE = "price_issue"
    CREDIT_HOLD = "credit_hold"
    COMPETITOR = "competitor"
    NOT_INTERESTED = "not_interested"
    OTHER = "other"


class JustificationCode(str, enum.Enum):
    """Why a rep started a visit away from the target (soft block)."""

    SHOP_RELOCATED = "shop_relocated"
    MET_OUTSIDE = "met_outside"
    GPS_POOR = "gps_poor"
    CUSTOMER_LOCATION_WRONG = "customer_location_wrong"
    OTHER = "other"


class VisitCancellationReason(str, enum.Enum):
    USER = "user"
    SHIFT_AUTO_CLOSED = "shift_auto_closed"
    SUPERSEDED = "superseded"
    MANAGER = "manager"
    DUPLICATE = "duplicate"


class ParticipantRole(str, enum.Enum):
    JOINT_WORKING = "joint_working"
    TRAINEE = "trainee"
    OBSERVER = "observer"
    BACKUP = "backup"


class TaskType(str, enum.Enum):
    TAKE_ORDER = "take_order"
    RECORD_NO_ORDER = "record_no_order"
    COLLECT_PAYMENT = "collect_payment"
    DELIVER = "deliver"
    PROCESS_RETURN = "process_return"
    PROCESS_EXCHANGE = "process_exchange"
    STOCK_CHECK = "stock_check"
    PRODUCT_DETAILING = "product_detailing"
    DISTRIBUTE_SAMPLE = "distribute_sample"
    SURVEY = "survey"
    MERCHANDISING = "merchandising"
    CUSTOMER_FEEDBACK = "customer_feedback"
    NOTE = "note"


class TaskStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    VOIDED = "voided"


class PingKind(str, enum.Enum):
    CONTINUOUS = "continuous"
    CHECKPOINT = "checkpoint"
    MANUAL = "manual"


class CheckpointLabel(str, enum.Enum):
    SHIFT_START = "shift_start"
    SHIFT_END = "shift_end"
    SHIFT_PAUSE = "shift_pause"
    SHIFT_RESUME = "shift_resume"
    VISIT_START = "visit_start"
    VISIT_END = "visit_end"
    TASK_SUBMITTED = "task_submitted"
    SOS = "sos"


SHIFT_LABELS = (CheckpointLabel.SHIFT_START.value, CheckpointLabel.SHIFT_END.value,
                CheckpointLabel.SHIFT_PAUSE.value, CheckpointLabel.SHIFT_RESUME.value)
VISIT_LABELS = (CheckpointLabel.VISIT_START.value, CheckpointLabel.VISIT_END.value,
                CheckpointLabel.TASK_SUBMITTED.value)


class LocationProvider(str, enum.Enum):
    GPS = "gps"
    FUSED = "fused"
    NETWORK = "network"
    PASSIVE = "passive"
    MANUAL = "manual"


class ActivityType(str, enum.Enum):
    STILL = "still"
    WALKING = "walking"
    RUNNING = "running"
    ON_BICYCLE = "on_bicycle"
    IN_VEHICLE = "in_vehicle"
    UNKNOWN = "unknown"


MOVING_ACTIVITIES = (ActivityType.WALKING.value, ActivityType.RUNNING.value,
                     ActivityType.ON_BICYCLE.value, ActivityType.IN_VEHICLE.value)


class QualityFlag(enum.IntFlag):
    """``location_pings.quality_flags`` bits. ``fieldops.v_ping_flags`` expands them in SQL."""

    NONE = 0
    LOW_ACCURACY = 1
    MOCK = 2
    IMPOSSIBLE_SPEED = 4
    CLOCK_SKEW = 8
    CLOCK_TAMPERED = 16
    PARTITION_KEY_CLAMPED = 32
    FOREIGN_DEVICE = 64
    OUT_OF_ORDER = 128
    STALE_REPLAY = 256
    DUPLICATE_COORDINATES = 512
    DURING_PAUSE = 1024


#: Fixes carrying any of these bits are never evidence (verification) nor counted as movement (metrics).
UNTRUSTED_FLAGS = QualityFlag.MOCK | QualityFlag.IMPOSSIBLE_SPEED | QualityFlag.DUPLICATE_COORDINATES


class CheckResult(str, enum.Enum):
    INSIDE = "inside"
    OUTSIDE = "outside"
    UNCERTAIN = "uncertain"
    NO_FIX = "no_fix"
    NOT_CONFIGURED = "not_configured"
    NOT_APPLICABLE = "not_applicable"


class TargetKind(str, enum.Enum):
    POLYGON = "polygon"
    CIRCLE = "circle"
    PLACE_DEFAULT = "place_default"
    NONE = "none"


class CheckPhase(str, enum.Enum):
    START = "start"
    END = "end"
    REVALIDATION = "revalidation"


class CheckAction(str, enum.Enum):
    RECORDED = "recorded"
    JUSTIFICATION_REQUIRED = "justification_required"
    BLOCKED = "blocked"
    JUSTIFIED = "justified"
    BYPASSED_OFFLINE = "bypassed_offline"


class SubjectType(str, enum.Enum):
    SHIFT = "shift"
    VISIT = "visit"
    VISIT_TASK = "visit_task"
    SHIFT_PAUSE = "shift_pause"
    PLACE = "place"
    DEVICE = "device"


class TransitionAxis(str, enum.Enum):
    LIFECYCLE = "lifecycle"
    REVIEW = "review"


class TransitionSource(str, enum.Enum):
    DEVICE = "device"
    SERVER = "server"
    SYSTEM = "system"
    MANAGER = "manager"


class AnomalyType(str, enum.Enum):
    GHOST_SHIFT = "ghost_shift"
    AUTO_CLOSED = "auto_closed"
    SUPERSEDED_SHIFT = "superseded_shift"
    LONG_GAP = "long_gap"
    LONG_PAUSE = "long_pause"
    TOO_MANY_PAUSES = "too_many_pauses"
    LOW_TRACKING_COVERAGE = "low_tracking_coverage"
    TRACKING_DISABLED = "tracking_disabled"
    MOCK_LOCATION = "mock_location"
    IMPOSSIBLE_SPEED = "impossible_speed"
    CLOCK_SKEW = "clock_skew"
    CLOCK_TAMPERED = "clock_tampered"
    FOREIGN_DEVICE = "foreign_device"
    OUTSIDE_GEOFENCE = "outside_geofence"
    JUSTIFIED_OUTSIDE = "justified_outside"
    HARD_BLOCK_BYPASSED_OFFLINE = "hard_block_bypassed_offline"
    MANUAL_LOCATION = "manual_location"
    SHORT_VISIT = "short_visit"
    VISIT_WITHOUT_SHIFT = "visit_without_shift"
    LATE_TASK = "late_task"
    EARLY_START = "early_start"
    LATE_END = "late_end"
    DISPUTED_PLACE = "disputed_place"
    PLACE_GEOTAG_PROPOSAL = "place_geotag_proposal"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AnomalyState(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Platform(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class LocationPermission(str, enum.Enum):
    ALWAYS = "always"
    WHILE_IN_USE = "while_in_use"
    DENIED = "denied"


class DeviceEventType(str, enum.Enum):
    GPS_DISABLED = "gps_disabled"
    GPS_ENABLED = "gps_enabled"
    PERMISSION_CHANGED = "permission_changed"
    AIRPLANE_ON = "airplane_on"
    AIRPLANE_OFF = "airplane_off"
    POWER_SAVE_ON = "power_save_on"
    POWER_SAVE_OFF = "power_save_off"
    TIME_CHANGED = "time_changed"
    TIMEZONE_CHANGED = "timezone_changed"
    APP_RESTARTED_AFTER_KILL = "app_restarted_after_kill"
    BOOT = "boot"
    MOCK_APP_DETECTED = "mock_app_detected"
    LOW_BATTERY = "low_battery"
    TRACKING_PAUSED = "tracking_paused"
    TRACKING_RESUMED = "tracking_resumed"


#: Device events that, during an open shift, mean tracking stopped (anomaly ``tracking_disabled``).
TRACKING_LOSS_EVENTS = (DeviceEventType.GPS_DISABLED.value, DeviceEventType.PERMISSION_CHANGED.value,
                        DeviceEventType.TRACKING_PAUSED.value)


class IdempotencyState(str, enum.Enum):
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
