"""Shifts — the work session container — its pauses, and its derived metrics.

Lifecycle (``state.py`` is the only writer)::

    scheduled ─start─▶ active ⇄ paused ─end─▶ completed
                         │         └──────auto_close─▶ auto_closed   (review pending)
                         └──supersede─▶ auto_closed (end_reason superseded)
    scheduled / active (no visits) ─cancel─▶ cancelled

``active`` and ``paused`` are both OPEN. ``uq_shifts_one_open`` allows at most one open
shift per user — a paused shift still blocks a second start, because the worker is
still on shift.

A pause is a ``ShiftPause`` row (a meal break, prayer, vehicle breakdown, network outage …).
While paused no visit may start and, unless the policy says ``track_during_pause``, the app
stops tracking. Whether pause time is paid is POLICY (``work_policies.paid_pause_types``),
frozen onto the pause row as ``is_paid`` when it starts.

Times: every business time is ``occurred_at``-derived (``clock.py``) and carries a
``*_received_at`` (when the server learned it) and ``*_time_basis`` (how it was derived).
Coordinates are NEVER stored here — the start/end/pause/resume fixes are checkpoint rows
of ``fieldops.location_pings``.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    BigIntPKWithUUIDv7Mixin,
    MultiTenantMixin,
    OrgEntityMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.comments.mixins import HasCommentsMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    CheckResult,
    DurationBasis,
    EndedBy,
    PauseEndReason,
    PauseType,
    ReviewStatus,
    ShiftEndReason,
    ShiftStatus,
    TimeBasis,
    TravelMode,
    values,
)

_LIVE = text("deleted_at IS NULL")


class Shift(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, HasCommentsMixin, Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_shifts_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_shifts_user", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "device_id"], [f"{FIELDOPS_SCHEMA}.devices.tenant_id",
                                                          f"{FIELDOPS_SCHEMA}.devices.id"],
                             name="fk_shifts_device", ondelete="RESTRICT"),
        CheckConstraint(f"status IN ({values(ShiftStatus)})", name="chk_shifts_status"),
        CheckConstraint(f"review_status IN ({values(ReviewStatus)})", name="chk_shifts_review_status"),
        CheckConstraint(f"ended_by IS NULL OR ended_by IN ({values(EndedBy)})", name="chk_shifts_ended_by"),
        CheckConstraint(f"end_reason IS NULL OR end_reason IN ({values(ShiftEndReason)})",
                        name="chk_shifts_end_reason"),
        CheckConstraint(f"duration_basis IS NULL OR duration_basis IN ({values(DurationBasis)})",
                        name="chk_shifts_duration_basis"),
        CheckConstraint(f"start_time_basis IS NULL OR start_time_basis IN ({values(TimeBasis)})",
                        name="chk_shifts_start_time_basis"),
        CheckConstraint(f"end_time_basis IS NULL OR end_time_basis IN ({values(TimeBasis)})",
                        name="chk_shifts_end_time_basis"),
        CheckConstraint(f"travel_mode IS NULL OR travel_mode IN ({values(TravelMode)})",
                        name="chk_shifts_travel_mode"),
        CheckConstraint(f"start_check IN ({values(CheckResult)})", name="chk_shifts_start_check"),
        CheckConstraint("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
                        name="chk_shifts_end_after_start"),
        CheckConstraint("status NOT IN ('active','paused') OR (started_at IS NOT NULL AND ended_at IS NULL)",
                        name="chk_shifts_open_has_start"),
        CheckConstraint("(status = 'paused') = (paused_since IS NOT NULL)", name="chk_shifts_paused_since"),
        CheckConstraint("status NOT IN ('completed','auto_closed') OR ended_at IS NOT NULL",
                        name="chk_shifts_closed_has_end"),
        CheckConstraint("odometer_end_km IS NULL OR odometer_start_km IS NULL OR odometer_end_km >= odometer_start_km",
                        name="chk_shifts_odometer"),
        CheckConstraint("pause_count >= 0", name="chk_shifts_pause_count"),
        # THE rule: at most one OPEN (active or paused) shift per user.
        Index("uq_shifts_one_open", "tenant_id", "user_id", unique=True,
              postgresql_where=text("status IN ('active','paused') AND deleted_at IS NULL")),
        Index("ix_shifts_user_date", "tenant_id", "user_id", text("shift_date DESC"), postgresql_where=_LIVE),
        Index("ix_shifts_org_date", "tenant_id", "organization_id", "shift_date", "status", postgresql_where=_LIVE),
        Index("ix_shifts_review", "tenant_id", "shift_date",
              postgresql_where=text("review_status = 'pending' AND deleted_at IS NULL")),
        Index("ix_shifts_open", "last_activity_at",
              postgresql_where=text("status IN ('active','paused') AND deleted_at IS NULL")),
        {"schema": FIELDOPS_SCHEMA, "comment": "Work sessions; at most one open (active|paused) per user."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    device_id: Mapped[int | None] = mapped_column(BigInteger, comment="The device the shift is bound to")
    policy_id: Mapped[int | None] = mapped_column(BigInteger, comment="work_policies.id resolved at start (no FK)")
    policy_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="The effective policy values frozen at start — old shifts are judged by the rules then in force",
    )
    shift_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, comment="Business day of the start in the ORGANIZATION's timezone, frozen",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ShiftStatus.ACTIVE.value,
                                        server_default=text("'active'"), index=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReviewStatus.NOT_REQUIRED.value,
                                               server_default=text("'not_required'"))

    planned_start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
                                                           comment="occurred_at of the start (clock.py)")
    start_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    start_time_basis: Mapped[str | None] = mapped_column(String(24))
    start_client_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Device wall clock at the start, as reported (raw)",
    )
    start_check: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CheckResult.NOT_CONFIGURED.value,
        server_default=text("'not_configured'"), comment="Start-place check (policy.require_start_at_place_id)",
    )
    start_manual_location_reason: Mapped[str | None] = mapped_column(Text)
    start_selfie_media_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))

    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_time_basis: Mapped[str | None] = mapped_column(String(24))
    end_client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[str | None] = mapped_column(String(10))
    end_reason: Mapped[str | None] = mapped_column(String(24))

    # ── pauses (detail rows in fieldops.shift_pauses) ─────────────────────────
    paused_since: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Start of the CURRENT pause; NULL unless status = 'paused'",
    )
    pause_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    pause_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment="All pause time, closed shifts")
    unpaid_pause_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2),
                                                                 comment="Pause time deducted from paid time")

    last_activity_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Max occurred_at of any ping/visit/task/pause; Core UPDATE with GREATEST, no row_version bump",
    )

    # ── attendance numbers ────────────────────────────────────────────────────
    wall_clock_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    paid_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2),
                                                         comment="Wall clock minus unpaid pauses — payroll")
    duration_basis: Mapped[str | None] = mapped_column(String(20))

    # ── travel ───────────────────────────────────────────────────────────────
    vehicle_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vehicles.id", ondelete="SET NULL"))
    travel_mode: Mapped[str | None] = mapped_column(String(20))
    odometer_start_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    odometer_end_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))

    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text, comment="Current summary; the note stream is comments")
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_open(self) -> bool:
        return self.status in (ShiftStatus.ACTIVE.value, ShiftStatus.PAUSED.value)

    def __repr__(self) -> str:
        return f"<Shift id={self.id} user={self.user_id} {self.shift_date} {self.status}>"


class ShiftPause(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "shift_pauses"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "shift_id"], [f"{FIELDOPS_SCHEMA}.shifts.tenant_id",
                                                         f"{FIELDOPS_SCHEMA}.shifts.id"],
                             name="fk_shift_pauses_shift", ondelete="CASCADE"),
        CheckConstraint(f"pause_type IN ({values(PauseType)})", name="chk_shift_pauses_type"),
        CheckConstraint(f"end_reason IS NULL OR end_reason IN ({values(PauseEndReason)})",
                        name="chk_shift_pauses_end_reason"),
        CheckConstraint(f"ended_by IS NULL OR ended_by IN ({values(EndedBy)})", name="chk_shift_pauses_ended_by"),
        CheckConstraint(f"start_time_basis IN ({values(TimeBasis)})", name="chk_shift_pauses_start_basis"),
        CheckConstraint(f"end_time_basis IS NULL OR end_time_basis IN ({values(TimeBasis)})",
                        name="chk_shift_pauses_end_basis"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chk_shift_pauses_end_after_start"),
        CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="chk_shift_pauses_end_reason_set"),
        # At most one open pause per shift.
        Index("uq_shift_pauses_one_open", "tenant_id", "shift_id", unique=True,
              postgresql_where=text("ended_at IS NULL AND deleted_at IS NULL")),
        Index("ix_shift_pauses_shift", "shift_id", "started_at", postgresql_where=_LIVE),
        {"schema": FIELDOPS_SCHEMA, "comment": "Pauses of a shift (breaks, outages …); paid-ness frozen from policy."},
    )

    shift_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pause_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"),
                                          comment="Frozen from policy.paid_pause_types at pause start")
    tracking_suspended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="True = the app was told to stop tracking during this pause (policy.track_during_pause false)",
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_time_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    start_client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_time_basis: Mapped[str | None] = mapped_column(String(24))
    end_client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[str | None] = mapped_column(String(10))
    end_reason: Mapped[str | None] = mapped_column(String(20))

    @property
    def minutes(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() / 60

    def __repr__(self) -> str:
        return f"<ShiftPause id={self.id} shift={self.shift_id} {self.pause_type}>"


class ShiftMetrics(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, TimestampMixin, Base):
    """KPIs of one shift. Derived and recomputable (``service/metrics.py``): upserted, never
    edited by hand. Field and telephonic figures are SEPARATE columns everywhere — phone
    orders must not inflate field coverage."""

    __tablename__ = "shift_metrics"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "shift_id"], [f"{FIELDOPS_SCHEMA}.shifts.tenant_id",
                                                         f"{FIELDOPS_SCHEMA}.shifts.id"],
                             name="fk_shift_metrics_shift", ondelete="CASCADE"),
        UniqueConstraint("shift_id", name="uq_shift_metrics_shift"),
        {"schema": FIELDOPS_SCHEMA, "comment": "Derived KPIs per shift (recomputable; metrics_version)."},
    )

    shift_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    metrics_version: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs_hash: Mapped[str | None] = mapped_column(String(64), comment="Skip the write when inputs are unchanged")

    # time
    wall_clock_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    pause_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    paid_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    engaged_minutes: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), comment="Visit time + travel between first and last visit — productivity, NOT payroll",
    )
    visit_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    travel_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    idle_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    first_visit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_visit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # tracking health
    fix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    accepted_fix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    tracking_coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    longest_gap_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    mock_fix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    low_accuracy_fix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    clock_skew_max_s: Mapped[int | None] = mapped_column(Integer)
    # movement
    gps_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    odometer_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    # visits
    visits_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_cancelled: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_unplanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    field_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    telephonic_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    video_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    productive_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # geofence (denominator = visits that had a target; NULL, never 0, when nothing was checkable)
    visits_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_inside: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_outside: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    visits_uncertain: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    geofence_compliance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # commercial (from visit_tasks.amount; one currency per shift in practice — the base column says which)
    orders_field: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    orders_telephonic: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    order_value_field: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0),
                                                       server_default=text("0"))
    order_value_telephonic: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0),
                                                            server_default=text("0"))
    collections_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal(0),
                                                       server_default=text("0"))
    currency_code: Mapped[str | None] = mapped_column(String(3), comment="NULL when no amount was recorded")
    # review
    anomaly_count_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))

    def __repr__(self) -> str:
        return f"<ShiftMetrics shift={self.shift_id} v{self.metrics_version}>"
