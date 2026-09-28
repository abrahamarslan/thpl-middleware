"""History and attention: state transitions and anomalies.

``StateTransition``  every lifecycle and review transition of shifts, pauses, visits and
                     tasks — who, when (business and receipt time, plus the raw client
                     timestamp), from where (device / server / system / manager), and for a
                     manager correction the field-level diff. Replaces the JSONB
                     ``status_history`` / ``revision_history`` arrays of the pasted design,
                     which lose concurrent updates and bloat hot rows (improvement F-24).
                     ``state.transition()`` is the only writer. LEDGER.
``Anomaly``          something a manager must look at (a ghost shift, a long pause, a mock
                     fix, an offline hard-block bypass …). Detectors are idempotent through
                     ``dedupe_key``. ENTITY: it has a resolution lifecycle in ``status``.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    BigIntPKWithUUIDv7Mixin,
    MultiTenantMixin,
    OrgEntityMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.fieldops.enums import (
    FIELDOPS_SCHEMA,
    AnomalyState,
    AnomalyType,
    Severity,
    SubjectType,
    TimeBasis,
    TransitionAxis,
    TransitionSource,
    values,
)


class StateTransition(BigIntPKWithUUIDv7Mixin, MultiTenantMixin, AppMetaMixin, Base):
    __tablename__ = "state_transitions"
    __table_args__ = (
        Index("ix_state_transitions_subject", "subject_type", "subject_id", "occurred_at"),
        CheckConstraint(f"subject_type IN ({values(SubjectType)})", name="chk_state_transitions_subject"),
        CheckConstraint(f"axis IN ({values(TransitionAxis)})", name="chk_state_transitions_axis"),
        CheckConstraint(f"source IN ({values(TransitionSource)})", name="chk_state_transitions_source"),
        CheckConstraint(f"time_basis IN ({values(TimeBasis)})", name="chk_state_transitions_time_basis"),
        {"schema": FIELDOPS_SCHEMA, "comment": "Every lifecycle/review transition (append-only)."},
    )

    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    axis: Mapped[str] = mapped_column(String(12), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(20))
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    time_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    client_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
                                                                 comment="Device wall clock as reported (raw)")
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_label: Mapped[str | None] = mapped_column(String(255), comment="Display name or system:<component>")
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[uuid_lib.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    changes: Mapped[dict | None] = mapped_column(JSONB, comment='{"field": [before, after]} for corrections')


class Anomaly(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        CheckConstraint(f"anomaly_type IN ({values(AnomalyType)})", name="chk_anomalies_type"),
        CheckConstraint(f"severity IN ({values(Severity)})", name="chk_anomalies_severity"),
        CheckConstraint(f"status IN ({values(AnomalyState)})", name="chk_anomalies_status"),
        CheckConstraint(f"subject_type IN ({values(SubjectType)})", name="chk_anomalies_subject"),
        # Detectors are idempotent: the same finding twice is one row.
        Index("uq_anomalies_dedupe", "tenant_id", "dedupe_key", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_anomalies_queue", "tenant_id", "organization_id", "status", text("detected_at DESC"),
              postgresql_where=text("deleted_at IS NULL")),
        Index("ix_anomalies_shift", "shift_id", postgresql_where=text("shift_id IS NOT NULL")),
        Index("ix_anomalies_subject", "subject_type", "subject_id"),
        {"schema": FIELDOPS_SCHEMA, "comment": "Things a manager must review; status = open/acknowledged/…"},
    )

    anomaly_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AnomalyState.OPEN.value,
                                        server_default=text("'open'"), index=True)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    shift_id: Mapped[int | None] = mapped_column(BigInteger)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                     server_default=text("now()"))
    detector: Mapped[str] = mapped_column(String(64), nullable=False, comment="system:fieldops-<detector>")
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    resolved_by: Mapped[int | None] = mapped_column(BigInteger)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_code: Mapped[str | None] = mapped_column(String(40))
    resolution_note: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<Anomaly {self.anomaly_type} {self.subject_type}:{self.subject_id} {self.status}>"
