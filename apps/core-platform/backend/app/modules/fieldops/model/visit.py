"""Visits — one customer engagement (field, telephonic or video) — and what was done in it.

Lifecycle::

    planned ─start─▶ in_progress ─end─▶ completed
       │ └─(day over)─▶ missed        │
       └─cancel─▶ cancelled ◀─cancel──┘   (incl. cascade: shift_auto_closed / superseded)

``uq_visits_one_in_progress`` is the database's "cannot be at two customers at once":
per USER, across shifts. Joint working does not break it — the accompanying manager is a
``VisitParticipant``, not the owner of a second visit.

The counterparty is named through the shared entity registry (``account_type`` →
``core.entity_types.code`` + ``account_id``), the same primitive tax assignments, aliases
and comments use; the WHERE is ``place_id`` → ``geo.places``. A visit stores timestamps and
verification HEADLINES only; the fixes are checkpoint rows of the stream and every
verification is a ``location_checks`` row.

Tasks (``VisitTask``) are what was done in the visit. ``performed_at`` is independent of
the visit window: a payment collected after "end visit" is recorded (``after_visit_end``),
never rejected. Payloads are validated per ``task_type`` by the registry in
``task_types.py``; ``reference_*`` point OUT to the owning module (orders, payments …).
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.comments.mixins import HasCommentsMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    Channel,
    CheckResult,
    JustificationCode,
    NoOrderReason,
    ParticipantRole,
    ReviewStatus,
    TaskStatus,
    TaskType,
    TimeBasis,
    VisitCancellationReason,
    VisitOutcome,
    VisitPurpose,
    VisitSource,
    VisitStatus,
    values,
)

_LIVE = text("deleted_at IS NULL")
_CORE_ENTITY_TYPES = "core.entity_types.code"


class Visit(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, HasCommentsMixin, Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_visits_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_visits_user", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "shift_id"], [f"{FIELDOPS_SCHEMA}.shifts.tenant_id",
                                                         f"{FIELDOPS_SCHEMA}.shifts.id"],
                             name="fk_visits_shift", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "place_id"], ["geo.places.tenant_id", "geo.places.id"],
                             name="fk_visits_place", ondelete="RESTRICT"),
        ForeignKeyConstraint(["account_type"], [_CORE_ENTITY_TYPES], name="fk_visits_account_type",
                             ondelete="RESTRICT"),
        CheckConstraint(f"channel IN ({values(Channel)})", name="chk_visits_channel"),
        CheckConstraint(f"status IN ({values(VisitStatus)})", name="chk_visits_status"),
        CheckConstraint(f"review_status IN ({values(ReviewStatus)})", name="chk_visits_review_status"),
        CheckConstraint(f"source IN ({values(VisitSource)})", name="chk_visits_source"),
        CheckConstraint(f"purpose IN ({values(VisitPurpose)})", name="chk_visits_purpose"),
        CheckConstraint(f"start_check IN ({values(CheckResult)})", name="chk_visits_start_check"),
        CheckConstraint(f"end_check IN ({values(CheckResult)})", name="chk_visits_end_check"),
        CheckConstraint(f"outcome IS NULL OR outcome IN ({values(VisitOutcome)})", name="chk_visits_outcome"),
        CheckConstraint(f"no_order_reason IS NULL OR no_order_reason IN ({values(NoOrderReason)})",
                        name="chk_visits_no_order_reason"),
        CheckConstraint(f"start_justification_code IS NULL OR start_justification_code IN "
                        f"({values(JustificationCode)})", name="chk_visits_justification"),
        CheckConstraint(f"cancellation_reason IS NULL OR cancellation_reason IN ({values(VisitCancellationReason)})",
                        name="chk_visits_cancellation_reason"),
        CheckConstraint(f"start_time_basis IS NULL OR start_time_basis IN ({values(TimeBasis)})",
                        name="chk_visits_start_time_basis"),
        CheckConstraint(f"end_time_basis IS NULL OR end_time_basis IN ({values(TimeBasis)})",
                        name="chk_visits_end_time_basis"),
        CheckConstraint("visit_time_basis IS NULL OR visit_time_basis IN ('button','geofence')",
                        name="chk_visits_visit_time_basis"),
        # A remote visit has no customer location to compare against.
        CheckConstraint("channel = 'field' OR (start_check = 'not_applicable' AND end_check = 'not_applicable')",
                        name="chk_visits_remote_not_applicable"),
        CheckConstraint("status <> 'in_progress' OR (started_at IS NOT NULL AND ended_at IS NULL)",
                        name="chk_visits_in_progress_open"),
        CheckConstraint("status <> 'completed' OR (started_at IS NOT NULL AND ended_at IS NOT NULL)",
                        name="chk_visits_completed_closed"),
        CheckConstraint("ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
                        name="chk_visits_end_after_start"),
        CheckConstraint("(account_type IS NULL) = (account_id IS NULL)", name="chk_visits_account_pair"),
        CheckConstraint("channel <> 'field' OR account_id IS NOT NULL OR place_id IS NOT NULL",
                        name="chk_visits_field_is_somewhere"),
        # THE rule: one in-progress visit per user, across shifts.
        Index("uq_visits_one_in_progress", "tenant_id", "user_id", unique=True,
              postgresql_where=text("status = 'in_progress' AND deleted_at IS NULL")),
        Index("ix_visits_shift", "shift_id", "started_at", postgresql_where=_LIVE),
        Index("ix_visits_user", "tenant_id", "user_id", text("started_at DESC"), postgresql_where=_LIVE),
        Index("ix_visits_account", "tenant_id", "account_type", "account_id", text("started_at DESC"),
              postgresql_where=text("account_id IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_visits_place", "place_id", text("started_at DESC"),
              postgresql_where=text("place_id IS NOT NULL AND deleted_at IS NULL")),
        Index("ix_visits_review", "tenant_id", "started_at",
              postgresql_where=text("review_status = 'pending' AND deleted_at IS NULL")),
        Index("ix_visits_plan", "plan_ref", postgresql_where=text("plan_ref IS NOT NULL")),
        {"schema": FIELDOPS_SCHEMA, "comment": "Customer engagements; at most one in_progress per user."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="The rep who owns the visit")
    shift_id: Mapped[int | None] = mapped_column(BigInteger, comment="NULL only when the policy allows it")
    device_id: Mapped[int | None] = mapped_column(BigInteger)
    channel: Mapped[str] = mapped_column(String(12), nullable=False, default=Channel.FIELD.value,
                                         server_default=text("'field'"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=VisitStatus.IN_PROGRESS.value,
                                        server_default=text("'in_progress'"), index=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default=ReviewStatus.NOT_REQUIRED.value,
                                               server_default=text("'not_required'"))
    source: Mapped[str] = mapped_column(String(12), nullable=False, default=VisitSource.UNPLANNED.value,
                                        server_default=text("'unplanned'"))
    plan_ref: Mapped[uuid_lib.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), comment="Beat/journey-plan item this fulfils (plans are a later module)",
    )
    sequence_in_plan: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default=VisitPurpose.SALES_CALL.value,
                                         server_default=text("'sales_call'"))
    account_type: Mapped[str | None] = mapped_column(String(64), comment="core.entity_types.code (customer, …)")
    account_id: Mapped[int | None] = mapped_column(BigInteger, comment="Id in the account type's table")
    place_id: Mapped[int | None] = mapped_column(BigInteger, comment="geo.places — where the visit happens")
    contact_person_ref: Mapped[uuid_lib.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), comment="Who was met — reserved for the contacts module",
    )

    planned_start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    start_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    start_time_basis: Mapped[str | None] = mapped_column(String(24))
    start_client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    end_time_basis: Mapped[str | None] = mapped_column(String(24))
    end_client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    geofence_entry_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="First fix of the first inside run lasting ≥ dwell (dwell detection)",
    )
    geofence_exit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    visit_time_basis: Mapped[str | None] = mapped_column(
        String(10), comment="button | geofence — which pair KPIs used",
    )

    start_check: Mapped[str] = mapped_column(String(20), nullable=False, default=CheckResult.NOT_CONFIGURED.value,
                                             server_default=text("'not_configured'"))
    end_check: Mapped[str] = mapped_column(String(20), nullable=False, default=CheckResult.NOT_CONFIGURED.value,
                                           server_default=text("'not_configured'"))
    distance_from_target_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    start_justification_code: Mapped[str | None] = mapped_column(String(40))
    start_justification_note: Mapped[str | None] = mapped_column(Text)
    manual_location_reason: Mapped[str | None] = mapped_column(Text)

    outcome: Mapped[str | None] = mapped_column(String(24))
    no_order_reason: Mapped[str | None] = mapped_column(String(40))
    follow_up_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(String(40))
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def duration_minutes(self) -> float | None:
        if self.started_at is None or self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() / 60

    def __repr__(self) -> str:
        return f"<Visit id={self.id} user={self.user_id} {self.channel} {self.status}>"


class VisitParticipant(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """Someone who joined a visit they do not own — joint working, a trainee, an observer."""

    __tablename__ = "visit_participants"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "visit_id"], [f"{FIELDOPS_SCHEMA}.visits.tenant_id",
                                                         f"{FIELDOPS_SCHEMA}.visits.id"],
                             name="fk_visit_participants_visit", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_visit_participants_user", ondelete="RESTRICT"),
        CheckConstraint(f"participant_role IN ({values(ParticipantRole)})", name="chk_visit_participants_role"),
        CheckConstraint("left_at IS NULL OR left_at >= joined_at", name="chk_visit_participants_window"),
        Index("uq_visit_participants_live", "tenant_id", "visit_id", "user_id", unique=True, postgresql_where=_LIVE),
        {"schema": FIELDOPS_SCHEMA, "comment": "Joint working: people who joined a visit they do not own."},
    )

    visit_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    participant_role: Mapped[str] = mapped_column(String(20), nullable=False,
                                                  default=ParticipantRole.JOINT_WORKING.value,
                                                  server_default=text("'joint_working'"))
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    left_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class VisitTask(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "visit_tasks"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "visit_id"], [f"{FIELDOPS_SCHEMA}.visits.tenant_id",
                                                         f"{FIELDOPS_SCHEMA}.visits.id"],
                             name="fk_visit_tasks_visit", ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_visit_tasks_user", ondelete="RESTRICT"),
        ForeignKeyConstraint(["reference_type"], [_CORE_ENTITY_TYPES], name="fk_visit_tasks_reference_type",
                             ondelete="RESTRICT"),
        CheckConstraint(f"task_type IN ({values(TaskType)})", name="chk_visit_tasks_type"),
        CheckConstraint(f"status IN ({values(TaskStatus)})", name="chk_visit_tasks_status"),
        CheckConstraint(f"time_basis IN ({values(TimeBasis)})", name="chk_visit_tasks_time_basis"),
        CheckConstraint("amount IS NULL OR currency_code IS NOT NULL", name="chk_visit_tasks_amount_currency"),
        CheckConstraint("currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'", name="chk_visit_tasks_currency"),
        CheckConstraint("status <> 'voided' OR void_reason IS NOT NULL", name="chk_visit_tasks_void_reason"),
        Index("ix_visit_tasks_visit", "visit_id", "task_type", postgresql_where=_LIVE),
        Index("ix_visit_tasks_reference", "reference_type", "reference_id",
              postgresql_where=text("reference_id IS NOT NULL")),
        Index("ix_visit_tasks_reference_uuid", "reference_uuid",
              postgresql_where=text("reference_uuid IS NOT NULL AND reference_id IS NULL")),
        {"schema": FIELDOPS_SCHEMA, "comment": "What was done in a visit (registry-validated payload)."},
    )

    visit_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Who performed it (may be a participant)")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=TaskStatus.SUBMITTED.value,
                                        server_default=text("'submitted'"), index=True)
    performed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                      comment="occurred_at — independent of the visit window")
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    time_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    after_visit_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Performed after the visit ended — recorded, never rejected",
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    payload_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    reference_type: Mapped[str | None] = mapped_column(String(64), comment="core.entity_types.code of the document")
    reference_id: Mapped[int | None] = mapped_column(BigInteger)
    reference_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), comment="Client uuid of a document created offline, until its module resolves it",
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    void_reason: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<VisitTask id={self.id} visit={self.visit_id} {self.task_type}>"


