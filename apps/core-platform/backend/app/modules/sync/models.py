"""The crosswalk tables — one sync store for every source and every module.

Three tables, three shapes, because sync bookkeeping is three workloads
(docs/implementation-plan/sync-crosswalk-redesign.md §2):

  SyncRecord        HOT. Exactly one row per (tenant, source, module, external
                    id). The apply gate's state AND the identity crosswalk that
                    turns a Zoho id into a local FK. Point-looked-up on every
                    payload, updated in place, so it is partitioned by LIST
                    (source_system) — a key every query carries, so pruning
                    always fires — and never by time (a time-partitioned table
                    cannot hold the UNIQUE that stops two lanes creating two
                    "current" rows, and a lookup with no time predicate would
                    fan out across every partition).
  SyncPayload       COLD. One row per applied CHANGE, append-only, RANGE
                    partitioned on synced_at so retention is a partition DROP.
  PendingReference  A queue: documents that referenced a master we had not
                    synced yet, waiting to be linked.

Tenancy conformance (tests/test_tenancy.py:186) — every table here carries
LEDGER_COLUMNS {tenant_id, organization_id, app_version, app_metadata}:

  * ``SyncPayload`` and ``PendingReference`` take ``LedgerMixin``
    (TenantScopedMixin + AppMetaMixin), which is exactly right: append-only
    operational rows, no row_version, no soft delete, no status.
  * ``SyncRecord`` must NOT be called a ledger — it is updated in place. It
    composes the same columns plus ``TimestampMixin`` (LedgerMixin has no
    timestamps). It deliberately carries no ``row_version``: the conformance
    test requires any table with one to also carry the full ENTITY_COLUMNS set
    (status, verification, audit users, soft delete), which a crosswalk row has
    no use for. Concurrency is handled by the guarded upsert in crosswalk.py,
    which is stronger than optimistic locking — the loser writes nothing and
    raises nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import AppMetaMixin, LedgerMixin, TenantScopedMixin, TimestampMixin

SYNC_SCHEMA = "sync"


class LinkState:
    """How firm the crosswalk's link to a local row is."""

    LINKED = "linked"            # entity_id points at a real, fully synced row
    PROVISIONAL = "provisional"  # a stub created to satisfy a reference; awaiting enrichment
    ORPHANED = "orphaned"        # the entity is gone; reported, never silently deleted


class SyncOutcome:
    """``SyncPayload.outcome`` — mirrors apply.Outcome, minus the no-ops.

    Only outcomes that WROTE append a payload row; ``unchanged`` and
    ``stale_ignored`` are the bulk of every scan and carry no information.
    """

    INSERTED = "inserted"
    UPDATED = "updated"
    RESURRECTED = "resurrected"
    TOMBSTONED = "tombstoned"


#: outcome -> retention policy class (the analogue of control.models.EVENT_CLASS,
#: which ZohoRetentionPolicy.event_class matches on). Used by the generalised
#: retention job in Phase 2.
PAYLOAD_CLASS = {
    SyncOutcome.INSERTED: "success",
    SyncOutcome.UPDATED: "success",
    SyncOutcome.RESURRECTED: "success",
    SyncOutcome.TOMBSTONED: "failure",
}


class SyncRecord(TenantScopedMixin, AppMetaMixin, TimestampMixin, Base):
    """One external record's identity and sync state. The crosswalk.

    NOT a ledger (updated in place) and NOT an entity (no status, no
    verification, no audit user, no soft delete) — see the module docstring.
    """

    __tablename__ = "sync_records"

    # The partition key is part of the PK, as Postgres requires.
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_system: Mapped[str] = mapped_column(
        Text, primary_key=True, comment="Partition key: 'zoho' | 'sap' | 'manual'",
    )

    # ── identity in the source ──────────────────────────────────────────────
    module: Mapped[str] = mapped_column(Text, comment="Registry key, e.g. 'currencies'")
    external_id: Mapped[str] = mapped_column(Text, comment="The source's primary key, verbatim")
    connection_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Which credential produced this row (no FK: sources differ)",
    )

    # ── identity locally (polymorphic: no FK is possible — §2.4) ────────────
    entity_table: Mapped[str] = mapped_column(
        Text, comment="Schema-qualified target table, e.g. 'currency.currencies'",
    )
    entity_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="PK in entity_table; NULL only while provisional",
    )
    link_state: Mapped[str] = mapped_column(
        Text, default=LinkState.LINKED, server_default=text(f"'{LinkState.LINKED}'"),
    )

    # ── apply-gate state (was ZohoMirrorMixin, on every entity table) ───────
    source_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="The source's version of the stored data (monotonic fence)",
    )
    raw: Mapped[dict | None] = mapped_column(
        JSONB, comment="Current richest document; overwritten in place (replay reads this)",
    )
    raw_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, comment="sha256 of raw minus volatile keys (apply-gate no-op check)",
    )
    raw_source: Mapped[str | None] = mapped_column(
        Text, comment="Provenance: list:<mode> | detail_fetch | nested:<parent> | webhook",
    )
    raw_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Tombstone evidence: when we learned the source deleted it",
    )
    sync_version: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"),
        comment="Applied-change counter; also the visible evidence of a winning upsert",
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # ── opt-in capture ──────────────────────────────────────────────────────
    custom_fields: Mapped[dict | None] = mapped_column(
        JSONB, comment="Source custom fields (JSONB, replacing the mirrors' HSTORE)",
    )
    comments: Mapped[dict | None] = mapped_column(JSONB, comment="Source comments/notes collection")

    __table_args__ = (
        # THE identity constraint. Includes the partition key, so it is legal on
        # a partitioned table — and it is the conflict target the guarded upsert
        # infers (crosswalk.upsert_record).
        Index("uq_sync_records_identity", "tenant_id", "source_system", "module", "external_id",
              unique=True),
        # Reverse lookup: "what does the source call this row?" + orphan sweeping.
        Index("ix_sync_records_entity", "entity_table", "entity_id"),
        # Reconciliation: the live ids of a module, without touching entity tables.
        Index("ix_sync_records_module_live", "tenant_id", "source_system", "module",
              postgresql_where=text("remote_deleted_at IS NULL")),
        Index("ix_sync_records_provisional", "tenant_id", "module",
              postgresql_where=text(f"link_state = '{LinkState.PROVISIONAL}'")),
        {"schema": SYNC_SCHEMA,
         "postgresql_partition_by": "LIST (source_system)",
         "comment": "Crosswalk: one row per (tenant, source, module, external id)."},
    )

    def __repr__(self) -> str:
        return (
            f"<SyncRecord {self.source_system}:{self.module}:{self.external_id} "
            f"-> {self.entity_table}#{self.entity_id} v{self.sync_version}>"
        )


class SyncPayload(LedgerMixin, Base):
    """Append-only history: one row per applied change. Never a no-op.

    ``raw`` is NULL when the module sets ``history_raw=False`` — high-volume
    document modules keep only the hash and the changed-field list here, while
    their current document still lives on the SyncRecord.
    """

    __tablename__ = "sync_payloads"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(),
        comment="Partition key (RANGE, monthly)",
    )

    sync_record_id: Mapped[int] = mapped_column(
        BigInteger, comment="Logical ref to sync_records.id (no FK: both sides partitioned)",
    )
    source_system: Mapped[str] = mapped_column(Text)
    module: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    entity_table: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)

    outcome: Mapped[str] = mapped_column(Text, comment="inserted | updated | resurrected | tombstoned")
    raw: Mapped[dict | None] = mapped_column(JSONB)
    raw_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    raw_source: Mapped[str | None] = mapped_column(Text)
    sync_version: Mapped[int | None] = mapped_column(BigInteger)
    changed_fields: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    __table_args__ = (
        Index("ix_sync_payloads_record", "sync_record_id", "synced_at"),
        Index("ix_sync_payloads_identity", "tenant_id", "source_system", "module", "external_id",
              "synced_at"),
        Index("ix_sync_payloads_run", "run_id"),
        {"schema": SYNC_SCHEMA,
         "postgresql_partition_by": "RANGE (synced_at)",
         "comment": "Append-only history of applied sync changes (retention = partition drop)."},
    )


class PendingReference(LedgerMixin, Base):
    """A document referenced a master we had not synced. Who is waiting for what.

    Drained by the reconcile lane: resolve through the crosswalk, write the FK
    onto the waiting row, delete this one. Also the honest answer to "what did
    we fail to link?" — a number an operator can watch, instead of silent NULLs.
    """

    __tablename__ = "pending_references"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)

    # what is missing
    source_system: Mapped[str] = mapped_column(Text)
    module: Mapped[str] = mapped_column(Text, comment="Module that owns the missing record")
    external_id: Mapped[str] = mapped_column(Text)

    # who is waiting for it
    waiting_table: Mapped[str] = mapped_column(Text, comment="Schema-qualified table of the waiting row")
    waiting_id: Mapped[int] = mapped_column(BigInteger)
    waiting_column: Mapped[str] = mapped_column(Text, comment="FK column to fill once resolved")

    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_system", "module", "external_id",
                         "waiting_table", "waiting_id", "waiting_column",
                         name="uq_pending_references_waiter"),
        Index("ix_pending_references_target", "tenant_id", "source_system", "module", "external_id"),
        {"schema": SYNC_SCHEMA,
         "comment": "Unresolved references waiting for their master record to arrive."},
    )


#: Column names the apply gate reads off a crosswalk row. The engine selects
#: these explicitly — never the whole entity — so the TOASTed ``raw`` document
#: is not de-TOASTed on every payload (§2.1, hot-path rule).
GATE_COLUMNS: tuple[str, ...] = (
    "id", "entity_id", "entity_table", "link_state", "source_modified_at",
    "raw_hash", "raw_source", "remote_deleted_at", "sync_version",
)


def gate_columns(model: type[Any] = SyncRecord) -> list[Any]:
    """The gate's SELECT list — explicit columns, never ``SELECT *``."""
    return [getattr(model, name) for name in GATE_COLUMNS]


__all__ = [
    "GATE_COLUMNS",
    "PAYLOAD_CLASS",
    "SYNC_SCHEMA",
    "LinkState",
    "PendingReference",
    "SyncOutcome",
    "SyncPayload",
    "SyncRecord",
    "gate_columns",
]
