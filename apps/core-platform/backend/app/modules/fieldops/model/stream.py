"""The location stream, its upload envelopes, and the verification ledger.

``LocationPing``   THE location history of the platform (it replaced
                   ``public.user_location_pings``). Continuous fixes AND labelled checkpoints
                   (shift start/end/pause/resume, visit start/end, task submitted) are rows of
                   the same table — a checkpoint is a row with ``kind='checkpoint'``.
``PingBatch``      one row per upload (``uuid`` = the client's batch id): the device clocks at
                   send, counts, per-item non-accepted results, the body's sha256. A re-sent
                   batch is answered from here without touching the stream.
``LocationCheck``  one row per geofence/location verification. Re-evaluating appends; the
                   newest row per (subject, phase) is authoritative, history is never rewritten.

Stream design (docs/fieldops/improvement-document.md F-13, F-16…F-21)
--------------------------------------------------------------------
* ``RANGE (recorded_at)``, monthly, with a DEFAULT partition from day one (a partitioned
  parent with no partition rejects every INSERT). ``recorded_at`` is the DEVICE fix time,
  clamped to [received − 45 d, received + 10 min] so one phone set to 2031 cannot put rows
  in the DEFAULT partition that would block creating that month's partition later.
* ``uuid`` is the CLIENT's id of the fix. It is stable across replays, and so is
  ``recorded_at`` (the device stores it), so ``uq_location_pings_client`` makes a replay a
  no-op. (A unique index on a partitioned table must include the partition key — which is
  exactly why the partition key cannot be the server's receipt time.)
* ``occurred_at`` is BUSINESS time (clock.py). ``client_timestamp`` is the raw device wall
  clock, kept for diagnostics; ``received_at`` is when the server learned it.
* ``shift_id`` / ``visit_id`` are independent and nullable (a visit fix carries both), with
  NO foreign keys: offline queues may deliver fixes before the entity, so the client's uuids
  are kept and ``link_orphan_pings`` back-fills the ids.
* Geography is stored; ``latitude`` / ``longitude`` are GENERATED (the ``geo.places`` pattern).
  No GiST index: every spatial question is asked of ONE user's time window, which the btree
  narrows first.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal

from geoalchemy2 import Geography
from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
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
from app.database.mixins import AppMetaMixin, BigIntPKWithUUIDv7Mixin, MultiTenantMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    ActivityType,
    AppState,
    BatteryState,
    CheckAction,
    CheckPhase,
    CheckpointLabel,
    CheckResult,
    Enforcement,
    LocationProvider,
    PingKind,
    SubjectType,
    TargetKind,
    TimeBasis,
    values,
)


class LocationPing(MultiTenantMixin, AppMetaMixin, Base):
    __tablename__ = "location_pings"
    __table_args__ = (
        PrimaryKeyConstraint("recorded_at", "id", name="pk_location_pings"),
        # Idempotency: a replayed fix is the same (user, uuid, recorded_at) → ON CONFLICT DO NOTHING.
        UniqueConstraint("tenant_id", "user_id", "uuid", "recorded_at", name="uq_location_pings_client"),
        # Users are soft-deleted, so this FK never fires on the hot path; it only proves the owner.
        ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
                             name="fk_location_pings_user", ondelete="CASCADE"),
        CheckConstraint(f"kind IN ({values(PingKind)})", name="chk_location_pings_kind"),
        CheckConstraint(f"checkpoint_label IS NULL OR checkpoint_label IN ({values(CheckpointLabel)})",
                        name="chk_location_pings_label"),
        CheckConstraint("checkpoint_label IS NULL OR kind = 'checkpoint'", name="chk_location_pings_label_kind"),
        CheckConstraint("checkpoint_label NOT IN ('visit_start','visit_end','task_submitted') "
                        "OR visit_uuid IS NOT NULL", name="chk_location_pings_visit_label"),
        CheckConstraint("checkpoint_label NOT IN ('shift_start','shift_end','shift_pause','shift_resume') "
                        "OR shift_uuid IS NOT NULL", name="chk_location_pings_shift_label"),
        CheckConstraint("checkpoint_label NOT IN ('geofence_enter','geofence_exit') OR geofence_uuid IS NOT NULL",
                        name="chk_location_pings_geofence_label"),
        CheckConstraint(f"app_state IS NULL OR app_state IN ({values(AppState)})", name="chk_location_pings_app_state"),
        CheckConstraint(f"battery_state IS NULL OR battery_state IN ({values(BatteryState)})",
                        name="chk_location_pings_battery_state"),
        CheckConstraint(f"provider IN ({values(LocationProvider)})", name="chk_location_pings_provider"),
        CheckConstraint(f"time_basis IN ({values(TimeBasis)})", name="chk_location_pings_time_basis"),
        CheckConstraint(f"activity_type IS NULL OR activity_type IN ({values(ActivityType)})",
                        name="chk_location_pings_activity"),
        CheckConstraint("provider <> 'manual' OR manual_reason IS NOT NULL", name="chk_location_pings_manual_reason"),
        CheckConstraint("battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100", name="chk_location_pings_battery"),
        CheckConstraint("activity_confidence IS NULL OR activity_confidence BETWEEN 0 AND 100",
                        name="chk_location_pings_activity_confidence"),
        CheckConstraint("accuracy_m IS NULL OR accuracy_m >= 0", name="chk_location_pings_accuracy"),
        CheckConstraint("heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)",
                        name="chk_location_pings_heading"),
        CheckConstraint("speed_mps IS NULL OR speed_mps >= 0", name="chk_location_pings_speed"),
        Index("ix_location_pings_user_time", "tenant_id", "user_id", text("occurred_at DESC")),
        Index("ix_location_pings_shift", "shift_id", "occurred_at", postgresql_where=text("shift_id IS NOT NULL")),
        Index("ix_location_pings_checkpoint", "tenant_id", "occurred_at",
              postgresql_where=text("kind = 'checkpoint'")),
        Index("ix_location_pings_unlinked", "received_at",
              postgresql_where=text("(shift_uuid IS NOT NULL AND shift_id IS NULL) "
                                    "OR (visit_uuid IS NOT NULL AND visit_id IS NULL)")),
        {"schema": FIELDOPS_SCHEMA,
         "postgresql_partition_by": "RANGE (recorded_at)",
         "comment": "THE location stream: continuous fixes + labelled checkpoints. Monthly partitions."},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    recorded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="PARTITION KEY: device fix time, clamped to [received-45d, received+10min]",
    )
    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, server_default=text("uuidv7()"),
        comment="The CLIENT's id of the fix (UUIDv7) — the idempotency key",
    )
    batch_id: Mapped[int | None] = mapped_column(BigInteger, comment="fieldops.ping_batches.id (no FK)")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    device_id: Mapped[int | None] = mapped_column(BigInteger, comment="fieldops.devices.id (no FK)")
    device_session_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    shift_id: Mapped[int | None] = mapped_column(BigInteger, comment="No FK — back-filled by link_orphan_pings")
    visit_id: Mapped[int | None] = mapped_column(BigInteger, comment="No FK — back-filled by link_orphan_pings")
    shift_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    visit_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default=PingKind.CONTINUOUS.value,
                                      server_default=text("'continuous'"))
    checkpoint_label: Mapped[str | None] = mapped_column(String(24))

    client_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Device wall clock of the fix as reported — raw, unclamped, untrusted",
    )
    elapsed_realtime_ms: Mapped[int | None] = mapped_column(BigInteger, comment="Monotonic clock at the fix")
    boot_count: Mapped[int | None] = mapped_column(Integer)
    sequence_no: Mapped[int | None] = mapped_column(BigInteger, comment="Per device session; gap/reorder diagnostics")
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     comment="BUSINESS time (clock.py)")
    time_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    clock_skew_ms: Mapped[int | None] = mapped_column(BigInteger, comment="received_at - device sent_at")

    coordinates: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        comment="WGS84 point; NULL for a checkpoint with no fix",
    )
    latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7), Computed("ST_Y(coordinates::geometry)", persisted=True), comment="GENERATED",
    )
    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7), Computed("ST_X(coordinates::geometry)", persisted=True), comment="GENERATED",
    )
    accuracy_m: Mapped[float | None] = mapped_column(REAL, comment="Horizontal accuracy (68% radius)")
    altitude_m: Mapped[float | None] = mapped_column(REAL)
    vertical_accuracy_m: Mapped[float | None] = mapped_column(REAL)
    heading_deg: Mapped[float | None] = mapped_column(REAL)
    heading_accuracy_deg: Mapped[float | None] = mapped_column(REAL)
    speed_mps: Mapped[float | None] = mapped_column(REAL)
    speed_accuracy_mps: Mapped[float | None] = mapped_column(REAL)
    provider: Mapped[str] = mapped_column(String(10), nullable=False, default=LocationProvider.GPS.value,
                                          server_default=text("'gps'"))
    satellites: Mapped[int | None] = mapped_column(SmallInteger)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    activity_type: Mapped[str | None] = mapped_column(String(12))
    activity_confidence: Mapped[int | None] = mapped_column(SmallInteger)
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    is_charging: Mapped[bool | None] = mapped_column(Boolean)
    power_save: Mapped[bool | None] = mapped_column(Boolean)
    network_type: Mapped[str | None] = mapped_column(String(10))
    quality_flags: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"),
                                               comment="Bitmask — enums.QualityFlag / fieldops.v_ping_flags")
    manual_reason: Mapped[str | None] = mapped_column(Text)
    place_id: Mapped[int | None] = mapped_column(BigInteger, comment="Checkpoints: the resolved place")
    geocode_call_id: Mapped[int | None] = mapped_column(BigInteger, comment="Checkpoints: geo.geocode_api_calls.id")
    address_label: Mapped[str | None] = mapped_column(Text, comment="Checkpoints: display snapshot")
    geofence_id: Mapped[int | None] = mapped_column(BigInteger, comment="geo.geofences.id the event names (no FK)")
    geofence_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True),
                                                                comment="Fence the client reported (enter/exit)")
    app_state: Mapped[str | None] = mapped_column(String(12), comment="foreground | background")
    battery_state: Mapped[str | None] = mapped_column(String(14))
    client_significant: Mapped[bool | None] = mapped_column(Boolean, comment="Client hint; diagnostics only")
    client_distance_m: Mapped[float | None] = mapped_column(REAL, comment="Client-computed hop; diagnostics only")
    extras: Mapped[dict | None] = mapped_column(JSONB, comment="Sparse vendor fields; NULL normally")

    def __repr__(self) -> str:
        return f"<LocationPing user={self.user_id} {self.kind} at={self.occurred_at}>"


class PingBatch(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, Base):
    __tablename__ = "ping_batches"
    __table_args__ = (
        Index("ix_ping_batches_user_time", "tenant_id", "user_id", text("received_at DESC")),
        {"schema": FIELDOPS_SCHEMA,
         "comment": "One row per ping upload (uuid = client batch id): envelope, counts, non-accepted items."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    device_id: Mapped[int | None] = mapped_column(BigInteger)
    device_session_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    client_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Device wall clock when the batch was SENT (X-Device-Sent-At)",
    )
    client_elapsed_ms: Mapped[int | None] = mapped_column(BigInteger, comment="Monotonic clock at send")
    client_boot_count: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    ingest_ms: Mapped[int | None] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    results: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
        comment="[{uuid, status, reason}] for NON-accepted items only",
    )
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_object_key: Mapped[str | None] = mapped_column(Text, comment="Archived raw body (object storage), if kept")
    raw_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class LocationCheck(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, Base):
    __tablename__ = "location_checks"
    __table_args__ = (
        Index("ix_location_checks_subject", "subject_type", "subject_id", "phase", text("evaluated_at DESC")),
        CheckConstraint(f"subject_type IN ({values(SubjectType)})", name="chk_location_checks_subject"),
        CheckConstraint(f"phase IN ({values(CheckPhase)})", name="chk_location_checks_phase"),
        CheckConstraint(f"result IN ({values(CheckResult)})", name="chk_location_checks_result"),
        CheckConstraint(f"target_kind IN ({values(TargetKind)})", name="chk_location_checks_target"),
        CheckConstraint(f"enforcement IN ({values(Enforcement)})", name="chk_location_checks_enforcement"),
        CheckConstraint(f"action_taken IN ({values(CheckAction)})", name="chk_location_checks_action"),
        {"schema": FIELDOPS_SCHEMA, "comment": "Location/geofence verification ledger (append-only)."},
    )

    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                      server_default=text("now()"))
    evaluator_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                            comment="The instant being verified (the action's occurred_at)")
    fix_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    fix_recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    fix_accuracy_m: Mapped[float | None] = mapped_column(REAL)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    geofence_id: Mapped[int | None] = mapped_column(BigInteger)
    place_id: Mapped[int | None] = mapped_column(BigInteger)
    radius_m: Mapped[float | None] = mapped_column(Double)
    distance_m: Mapped[float | None] = mapped_column(Double, comment="0 when a polygon covers the fix")
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    enforcement: Mapped[str] = mapped_column(String(20), nullable=False)
    action_taken: Mapped[str] = mapped_column(String(24), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB)
