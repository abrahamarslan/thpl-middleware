"""``fieldops.work_policies`` — what a field worker MUST do (obligations).

What a user MAY do is RBAC (``fieldops.field_work:use``, ``fieldops.telephonic_visit:create``).
What they MUST do — run a shift, be tracked, be inside the fence — does not compose by
union the way permissions do, so it lives here: a row per organization, optionally
narrowed to one role, resolved by the user's BASE role walking up the organization tree
(``service/policy.py``). Not a column on ``roles``: tenancy core must not know a feature
module (.importlinter), and a contextual grant must not switch an obligation on or off.

A shift freezes the effective values it started under (``shifts.policy_snapshot``), so
changing a policy mid-day affects the next shift, never a running one.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    Enforcement,
    TrackingMode,
    values,
)


class WorkPolicy(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "work_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_work_policies_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"],
                             name="fk_work_policies_role", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "require_start_at_place_id"], ["geo.places.tenant_id", "geo.places.id"],
                             name="fk_work_policies_start_place", ondelete="RESTRICT"),
        # One live policy per (organization, role); role NULL = the organization default.
        Index("uq_work_policies_target_live", "tenant_id", "organization_id", text("COALESCE(role_id, 0)"),
              unique=True, postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint(f"tracking_mode IN ({values(TrackingMode)})", name="chk_work_policies_tracking_mode"),
        CheckConstraint(f"geofence_enforcement IN ({values(Enforcement)})", name="chk_work_policies_enforcement"),
        CheckConstraint("status IN ('active','inactive')", name="chk_work_policies_status"),
        CheckConstraint(
            "ping_interval_s > 0 AND stationary_interval_s > 0 AND ping_min_distance_m >= 0 "
            "AND default_visit_radius_m > 0 AND geocoded_radius_factor >= 1 AND max_fix_accuracy_m > 0 "
            "AND max_shift_hours > 0 AND auto_close_grace_minutes >= 0 AND stale_shift_after_minutes > 0 "
            "AND max_pause_minutes > 0 AND max_pauses_per_shift > 0 AND late_task_window_hours >= 0 "
            "AND min_visit_minutes >= 0 AND gap_flag_minutes > 0 AND clock_skew_flag_seconds > 0 "
            "AND min_tracking_coverage_pct BETWEEN 0 AND 100",
            name="chk_work_policies_positive",
        ),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "Field-work obligations per organization (and optionally per role); frozen onto each shift."},
    )

    role_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="roles.id this policy targets; NULL = the organization's default",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # ── shift obligations ──────────────────────────────────────────────────
    requires_shift: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Visits and tracking need an open shift",
    )
    allow_visits_without_shift: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Ad-hoc visits outside a shift (managers)",
    )
    require_location_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="DPDP: an active location_tracking consent is required before a shift starts",
    )
    require_start_selfie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                       server_default=text("false"))
    require_odometer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                   server_default=text("false"))
    require_start_at_place_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Place the day should start at (e.g. the hub) — checked, advisory",
    )
    earliest_start_local: Mapped[dt.time | None] = mapped_column(Time, comment="Organization-local time; earlier → early_start anomaly")
    latest_end_local: Mapped[dt.time | None] = mapped_column(Time, comment="Organization-local time; later → late_end anomaly")
    max_shift_hours: Mapped[Decimal] = mapped_column(
        Numeric(4, 1), nullable=False, default=Decimal("12.0"), server_default=text("12.0"),
        comment="Auto-close cap when a shift has no planned end",
    )
    auto_close_grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60,
                                                          server_default=text("60"))
    stale_shift_after_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=240, server_default=text("240"),
        comment="An open shift idle this long is superseded by a new start from the same device",
    )

    # ── pauses ───────────────────────────────────────────────────────────────
    max_pause_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90, server_default=text("90"),
        comment="A longer pause raises long_pause",
    )
    max_pauses_per_shift: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default=text("6"))
    paid_pause_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=lambda: ["rest", "meeting", "training"],
        server_default=text("ARRAY['rest','meeting','training']::text[]"),
        comment="Pause types that stay paid time; every other type is deducted from paid_minutes",
    )
    track_during_pause: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="false = the app stops tracking while paused (purpose limitation)",
    )

    # ── tracking ─────────────────────────────────────────────────────────────
    tracking_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=TrackingMode.CONTINUOUS.value,
                                               server_default=text("'continuous'"))
    ping_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default=text("60"))
    stationary_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300,
                                                       server_default=text("300"))
    ping_min_distance_m: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default=text("50"))

    # ── geofencing ───────────────────────────────────────────────────────────
    geofence_enforcement: Mapped[str] = mapped_column(String(20), nullable=False, default=Enforcement.ADVISORY.value,
                                                      server_default=text("'advisory'"))
    default_visit_radius_m: Mapped[int] = mapped_column(Integer, nullable=False, default=100,
                                                        server_default=text("100"))
    geocoded_radius_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("2.50"), server_default=text("2.50"),
        comment="Radius multiplier for places whose coordinates are geocoded_only",
    )
    max_fix_accuracy_m: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default=text("100"),
        comment="Fixes less accurate than this are never evidence",
    )
    allow_manual_location: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                                        server_default=text("true"))

    # ── anomaly thresholds ───────────────────────────────────────────────────
    min_visit_minutes: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=Decimal("2.0"),
                                                       server_default=text("2.0"))
    late_task_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12, server_default=text("12"),
        comment="How long after a visit ends a task may still be submitted",
    )
    gap_flag_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default=text("30"))
    clock_skew_flag_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300,
                                                         server_default=text("300"))
    min_tracking_coverage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False,
                                                               default=Decimal("70.00"), server_default=text("70.00"))

    def __repr__(self) -> str:
        return f"<WorkPolicy id={self.id} org={self.organization_id} role={self.role_id} {self.name!r}>"
