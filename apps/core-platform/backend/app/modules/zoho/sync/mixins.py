"""Zoho table mixins — columns only, composed per capability.

A table mixes in only what its capabilities need (docs/zoho-sync-implementation/
apply-gate.md §5, target-architecture delta §10):

    pulled from Zoho          ⇒ ZohoIdentityMixin + ZohoMirrorMixin
    pushed to Zoho            ⇒ + ZohoPushableMixin
    needs admin approval      ⇒ + ZohoApprovalMixin
    Inventory document        ⇒ + ZohoWarehouseScopedMixin
    line items / sub-records  ⇒ ZohoChildMixin (instead of the above)

    class ZohoPicklist(IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin,
                       ZohoApprovalMixin, ZohoPushableMixin, ZohoWarehouseScopedMixin,
                       ZohoMirrorMixin, ZohoIdentityMixin, Base): ...

(The v1 ``ZohoEntityMixin`` alias was retired with ``zoho_organizations``;
organizations are now ``org_management.organizations`` — docs/tenancy/README.md.)

Doctrine (app/database/mixins.py): mixins carry columns and tiny helpers
only — never event listeners, relationships or Zoho calls. Behaviour lives in
the engine and services.

Schema doctrine:
  - every business/sync column is nullable — an incomplete Zoho payload must
    never violate a constraint and fail the sync;
  - ``zoho_raw`` keeps the full document so a Zoho schema change never loses
    data and Debezium streams the complete record regardless of mapping;
  - ``custom_fields`` is hstore (flat, GIN-indexable); the raw array stays in
    ``zoho_raw``.
  - each model declares its own partial unique index on the live ``zoho_id``
    (``WHERE deleted_at IS NULL AND zoho_id IS NOT NULL``).
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import HSTORE, JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class SyncStatus(str, Enum):
    """Values of the legacy ``sync_status`` column (String, not a DB enum, so
    new states never require a migration)."""

    PENDING = "pending"        # never synced
    QUEUED = "queued"          # a queue-log entry exists, worker not started
    SYNCING = "syncing"        # a worker is processing this row
    SYNCED = "synced"          # in sync with Zoho
    ERROR = "error"            # last attempt failed (see sync_error)
    CONFLICT = "conflict"      # inbound + outbound changed simultaneously
    DELETED = "deleted"        # deleted upstream / delete pushed to Zoho


class SyncState(str, Enum):
    """Values of ``ZohoPushableMixin.sync_state`` (tables built after the split)."""

    LOCAL_ONLY = "local_only"
    AWAITING_APPROVAL = "awaiting_approval"
    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    FAILED = "failed"
    DELETING = "deleting"


# ── identity ────────────────────────────────────────────────────────────────

class ZohoIdentityMixin:
    """Who the row is, in Zoho and locally.

    ``public_id`` is our own stable identifier: generated locally before any
    push, sent to Zoho as a correlation reference, so an ambiguous create can
    be matched back to its row (outbox identity lookup).
    """

    zoho_id: Mapped[str | None] = mapped_column(
        String(50), index=True, comment="Zoho primary key; NULL until first outbound push succeeds"
    )
    public_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, server_default=text("gen_random_uuid()"),
        comment="Local stable id; correlation reference sent to Zoho",
    )


# ── mirror (fed by pull) ────────────────────────────────────────────────────

class ZohoMirrorMixin:
    """What the apply gate needs to decide stale / unchanged / newer.

    ``zoho_raw`` is written only by the richest payload class seen for the
    current version (``sync_source`` says which), so a thin list row never
    overwrites a detail document (provenance).
    """

    zoho_raw: Mapped[dict | None] = mapped_column(JSONB, comment="Full untouched Zoho document")
    zoho_raw_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, comment="sha256 of zoho_raw minus volatile keys (apply-gate no-op check)"
    )
    zoho_raw_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    zoho_last_modified_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, comment="Zoho version of the stored data (monotonic fence)"
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_source: Mapped[str | None] = mapped_column(
        String(48), comment="Provenance of zoho_raw: list:<mode> | detail_fetch | nested:<parent> | webhook"
    )
    sync_version: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), comment="Incremented on every applied change"
    )
    remote_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Tombstone evidence: when the sync learned Zoho deleted it"
    )
    custom_fields: Mapped[dict | None] = mapped_column(
        HSTORE, comment="Zoho custom fields flattened to text (raw array in zoho_raw)"
    )


# ── push / approval / warehouse / child (column sets for the next modules) ──

class ZohoPushableMixin:
    """Local → Zoho state for tables with push capability."""

    sync_state: Mapped[str | None] = mapped_column(String(20), default=SyncState.LOCAL_ONLY.value, index=True)
    pending_command_id: Mapped[int | None] = mapped_column(BigInteger)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_push_error: Mapped[str | None] = mapped_column(Text)


class ZohoApprovalMixin:
    """Denormalised latest approval decision (the decisions table is the truth)."""

    approval_status: Mapped[str | None] = mapped_column(String(16), index=True)
    approval_requested_by: Mapped[int | None] = mapped_column(BigInteger)
    approval_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class ZohoWarehouseScopedMixin:
    """Inventory documents: where the stock moves (local FKs resolved lazily)."""

    location_zoho_id: Mapped[str | None] = mapped_column(String(50))
    warehouse_zoho_id: Mapped[str | None] = mapped_column(String(50))
    location_id: Mapped[int | None] = mapped_column(BigInteger)
    warehouse_id: Mapped[int | None] = mapped_column(BigInteger, index=True)


class ZohoChildMixin:
    """Line items and other sub-records of a Zoho document.

    Models declare ``parent_id`` as a real FK plus the unique indexes
    ``(parent_id, position)`` and ``(parent_id, zoho_sub_id) WHERE zoho_sub_id
    IS NOT NULL``.
    """

    zoho_sub_id: Mapped[str | None] = mapped_column(String(50), comment="e.g. line_item_id")
    position: Mapped[int | None] = mapped_column(Integer)
    zoho_raw: Mapped[dict | None] = mapped_column(JSONB, comment="The sub-document")
    local_only: Mapped[dict | None] = mapped_column(JSONB, comment="Local enrichments kept across re-syncs")


__all__ = [
    "SyncState",
    "SyncStatus",
    "ZohoApprovalMixin",
    "ZohoChildMixin",
    "ZohoIdentityMixin",
    "ZohoMirrorMixin",
    "ZohoPushableMixin",
    "ZohoWarehouseScopedMixin",
]
