"""Sync crosswalk — schema ``sync``: sync_records, sync_payloads, pending_references

The platform-wide store for "which external record is which local row, and what
state is its sync in" (docs/implementation-plan/sync-crosswalk-redesign.md).

Three tables, three shapes:

    sync.sync_records       HOT. One row per (tenant, source, module, external
                            id). Partitioned by LIST (source_system): every
                            engine query carries that key so pruning always
                            fires, the partition count stays at 3-5 forever, and
                            the UNIQUE identity index is legal because it
                            includes the partition key. Time partitioning was
                            rejected here: the gate lookup has no time
                            predicate, and a time-partitioned table cannot hold
                            the UNIQUE that stops two lanes creating two
                            "current" rows for one record.
    sync.sync_payloads      COLD. One row per applied CHANGE, append-only,
                            RANGE (synced_at) monthly, so retention is a
                            partition DROP. DEFAULT partition so an insert can
                            never fail for a missing month.
    sync.pending_references A queue of documents waiting for a master record.

Native partitioning (not pg_partman) for the same reason the control-plane
migration gives: the scratch test image does not ship pg_partman.

Additive and fully reversible: it creates a new schema and touches no existing
table. Nothing reads these tables until the engine opts a module in
(``SyncContract.crosswalk``, default False).

Revision ID: b8d31c7f4a52
Revises: ef2c15ee5df8
Create Date: 2026-09-21
"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d31c7f4a52"
down_revision: str | None = "ef2c15ee5df8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Months of sync_payloads partitions created up front; the retention job
#: (Phase 2) keeps the window rolling from there.
_MONTHS_AHEAD = 3


def _month_bounds(anchor: date, offset: int) -> tuple[str, date, date]:
    month_index = anchor.year * 12 + (anchor.month - 1) + offset
    year, month = divmod(month_index, 12)
    start = date(year, month + 1, 1)
    end_index = month_index + 1
    end_year, end_month = divmod(end_index, 12)
    end = date(end_year, end_month + 1, 1)
    return f"sync_payloads_p{start:%Y%m}", start, end


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sync")

    # ── sync.sync_records — the crosswalk (LIST-partitioned by source) ──────
    op.create_table(
        "sync_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False,
                  comment="Partition key: 'zoho' | 'sap' | 'manual'"),
        sa.Column("module", sa.Text(), nullable=False, comment="Registry key, e.g. 'currencies'"),
        sa.Column("external_id", sa.Text(), nullable=False,
                  comment="The source's primary key, verbatim"),
        sa.Column("connection_id", sa.BigInteger(), nullable=True,
                  comment="Which credential produced this row (no FK: sources differ)"),
        sa.Column("entity_table", sa.Text(), nullable=False,
                  comment="Schema-qualified target table, e.g. 'currency.currencies'"),
        sa.Column("entity_id", sa.BigInteger(), nullable=True,
                  comment="PK in entity_table; NULL only while provisional"),
        sa.Column("link_state", sa.Text(), server_default=sa.text("'linked'"), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True,
                  comment="The source's version of the stored data (monotonic fence)"),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Current richest document; overwritten in place (replay reads this)"),
        sa.Column("raw_hash", sa.LargeBinary(), nullable=True,
                  comment="sha256 of raw minus volatile keys (apply-gate no-op check)"),
        sa.Column("raw_source", sa.Text(), nullable=True,
                  comment="Provenance: list:<mode> | detail_fetch | nested:<parent> | webhook"),
        sa.Column("raw_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Tombstone evidence: when we learned the source deleted it"),
        sa.Column("sync_version", sa.BigInteger(), server_default=sa.text("0"), nullable=False,
                  comment="Applied-change counter; also the evidence of a winning upsert"),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Source custom fields (JSONB, replacing the mirrors' HSTORE)"),
        sa.Column("comments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id",
                                 "org_management.organizations.id"],
                                name="fk_sync_records_tenant_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="RESTRICT"),
        # The partition key must be part of the primary key.
        sa.PrimaryKeyConstraint("id", "source_system"),
        schema="sync",
        comment="Crosswalk: one row per (tenant, source, module, external id).",
        postgresql_partition_by="LIST (source_system)",
    )

    # One partition per source we know, plus a DEFAULT so an unknown source can
    # never fail an insert. Adding SAP later is one CREATE TABLE.
    for suffix, value in (("zoho", "zoho"), ("manual", "manual")):
        op.execute(
            f"CREATE TABLE sync.sync_records_{suffix} PARTITION OF sync.sync_records "
            f"FOR VALUES IN ('{value}')"
        )
    op.execute("CREATE TABLE sync.sync_records_default PARTITION OF sync.sync_records DEFAULT")

    # THE identity constraint: one crosswalk row per source record. Legal on a
    # partitioned table because it includes the partition key — and it is the
    # conflict target the engine's guarded upsert infers.
    op.create_index("uq_sync_records_identity", "sync_records",
                    ["tenant_id", "source_system", "module", "external_id"],
                    unique=True, schema="sync")
    op.create_index("ix_sync_records_entity", "sync_records", ["entity_table", "entity_id"],
                    unique=False, schema="sync")
    op.create_index("ix_sync_records_module_live", "sync_records",
                    ["tenant_id", "source_system", "module"], unique=False, schema="sync",
                    postgresql_where=sa.text("remote_deleted_at IS NULL"))
    op.create_index("ix_sync_records_provisional", "sync_records", ["tenant_id", "module"],
                    unique=False, schema="sync",
                    postgresql_where=sa.text("link_state = 'provisional'"))
    op.create_index("ix_sync_records_tenant_org", "sync_records", ["tenant_id", "organization_id"],
                    unique=False, schema="sync")
    op.create_index("ix_sync_sync_records_tenant_id", "sync_records", ["tenant_id"],
                    unique=False, schema="sync")

    # ``raw`` holds whole source documents; lz4 decompresses far faster than the
    # default pglz and these values are read on every replay.
    op.execute("ALTER TABLE sync.sync_records ALTER COLUMN raw SET COMPRESSION lz4")

    # ── sync.sync_payloads — append-only history (RANGE-partitioned) ────────
    op.create_table(
        "sync_payloads",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False, comment="Partition key (RANGE, monthly)"),
        sa.Column("sync_record_id", sa.BigInteger(), nullable=False,
                  comment="Logical ref to sync_records.id (no FK: both sides partitioned)"),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("entity_table", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False,
                  comment="inserted | updated | resurrected | tombstoned"),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_hash", sa.LargeBinary(), nullable=True),
        sa.Column("raw_source", sa.Text(), nullable=True),
        sa.Column("sync_version", sa.BigInteger(), nullable=True),
        sa.Column("changed_fields", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id",
                                 "org_management.organizations.id"],
                                name="fk_sync_payloads_tenant_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", "synced_at"),
        schema="sync",
        comment="Append-only history of applied sync changes (retention = partition drop).",
        postgresql_partition_by="RANGE (synced_at)",
    )

    op.execute("CREATE TABLE sync.sync_payloads_default PARTITION OF sync.sync_payloads DEFAULT")
    anchor = date.today().replace(day=1)
    for offset in range(_MONTHS_AHEAD):
        name, start, end = _month_bounds(anchor, offset)
        op.execute(
            f"CREATE TABLE sync.{name} PARTITION OF sync.sync_payloads "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )

    op.create_index("ix_sync_payloads_record", "sync_payloads", ["sync_record_id", "synced_at"],
                    unique=False, schema="sync")
    op.create_index("ix_sync_payloads_identity", "sync_payloads",
                    ["tenant_id", "source_system", "module", "external_id", "synced_at"],
                    unique=False, schema="sync")
    op.create_index("ix_sync_payloads_run", "sync_payloads", ["run_id"], unique=False, schema="sync")
    op.create_index("ix_sync_payloads_tenant_org", "sync_payloads", ["tenant_id", "organization_id"],
                    unique=False, schema="sync")
    op.create_index("ix_sync_sync_payloads_tenant_id", "sync_payloads", ["tenant_id"],
                    unique=False, schema="sync")
    op.execute("ALTER TABLE sync.sync_payloads ALTER COLUMN raw SET COMPRESSION lz4")

    # ── sync.pending_references — the waiting queue ─────────────────────────
    op.create_table(
        "pending_references",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("module", sa.Text(), nullable=False,
                  comment="Module that owns the missing record"),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("waiting_table", sa.Text(), nullable=False,
                  comment="Schema-qualified table of the waiting row"),
        sa.Column("waiting_id", sa.BigInteger(), nullable=False),
        sa.Column("waiting_column", sa.Text(), nullable=False,
                  comment="FK column to fill once resolved"),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id",
                                 "org_management.organizations.id"],
                                name="fk_pending_references_tenant_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_system", "module", "external_id",
                            "waiting_table", "waiting_id", "waiting_column",
                            name="uq_pending_references_waiter"),
        schema="sync",
        comment="Unresolved references waiting for their master record to arrive.",
    )
    op.create_index("ix_pending_references_target", "pending_references",
                    ["tenant_id", "source_system", "module", "external_id"],
                    unique=False, schema="sync")
    op.create_index("ix_pending_references_tenant_org", "pending_references",
                    ["tenant_id", "organization_id"], unique=False, schema="sync")
    op.create_index("ix_sync_pending_references_tenant_id", "pending_references", ["tenant_id"],
                    unique=False, schema="sync")


def downgrade() -> None:
    # Dropping a partitioned parent drops its partitions with it.
    op.drop_table("pending_references", schema="sync")
    op.drop_table("sync_payloads", schema="sync")
    op.drop_table("sync_records", schema="sync")
    op.execute("DROP SCHEMA IF EXISTS sync RESTRICT")
