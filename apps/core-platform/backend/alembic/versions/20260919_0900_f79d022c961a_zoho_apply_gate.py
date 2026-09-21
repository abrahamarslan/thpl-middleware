"""zoho apply gate: mirror columns on zoho_organizations + slice counters on runs

Mixin split (app/modules/zoho/sync/mixins.py): ``ZohoEntityMixin`` now
composes ``ZohoIdentityMixin`` + ``ZohoMirrorMixin``, which add the columns
the apply gate decides with (docs/zoho-sync-implementation/apply-gate.md):

  public_id                 local stable id (correlation reference for pushes)
  zoho_raw_hash             sha256 of the payload minus volatile keys (no-op check)
  zoho_raw_synced_at        when zoho_raw was last written
  zoho_last_modified_time   Zoho version of the stored data (monotonic fence)
  sync_source               provenance of zoho_raw (list / detail / nested)
  sync_version              incremented on every applied change
  remote_deleted_at         tombstone evidence time

Existing rows get a generated ``public_id`` and ``sync_version = 0``; the
first sync after deploy writes each row's hash once, after which identical
payloads no longer UPDATE.

zoho_sync_runs gains the gate outcome counters and the slice resume page.

Revision ID: f79d022c961a
Revises: e6f7a8b9c0d1
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f79d022c961a"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_COUNTERS = ("resurrected", "unchanged", "stale_ignored", "details_saved")


def upgrade() -> None:
    # ── zoho_organizations: ZohoIdentityMixin + ZohoMirrorMixin columns ─────
    op.add_column(
        "zoho_organizations",
        sa.Column("public_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  nullable=True, comment="Local stable id; correlation reference sent to Zoho"),
    )
    op.create_unique_constraint("zoho_organizations_public_id_key", "zoho_organizations", ["public_id"])
    op.add_column(
        "zoho_organizations",
        sa.Column("zoho_raw_hash", sa.LargeBinary(), nullable=True,
                  comment="sha256 of zoho_raw minus volatile keys (apply-gate no-op check)"),
    )
    op.add_column("zoho_organizations", sa.Column("zoho_raw_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "zoho_organizations",
        sa.Column("zoho_last_modified_time", sa.DateTime(timezone=True), nullable=True,
                  comment="Zoho version of the stored data (monotonic fence)"),
    )
    op.create_index(
        "ix_zoho_organizations_zoho_last_modified_time", "zoho_organizations", ["zoho_last_modified_time"]
    )
    op.add_column(
        "zoho_organizations",
        sa.Column("sync_source", sa.String(48), nullable=True,
                  comment="Provenance of zoho_raw: list:<mode> | detail_fetch | nested:<parent> | webhook"),
    )
    op.add_column(
        "zoho_organizations",
        sa.Column("sync_version", sa.BigInteger(), server_default=sa.text("0"), nullable=False,
                  comment="Incremented on every applied change"),
    )
    op.add_column(
        "zoho_organizations",
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Tombstone evidence: when the sync learned Zoho deleted it"),
    )

    # ── zoho_sync_runs: apply-gate outcomes + slice resume ──────────────────
    for column in _RUN_COUNTERS:
        op.add_column("zoho_sync_runs", sa.Column(column, sa.Integer(), server_default=sa.text("0"), nullable=False))
    op.add_column("zoho_sync_runs", sa.Column("start_page", sa.Integer(), nullable=True))
    op.add_column("zoho_sync_runs", sa.Column("next_page", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("zoho_sync_runs", "next_page")
    op.drop_column("zoho_sync_runs", "start_page")
    for column in reversed(_RUN_COUNTERS):
        op.drop_column("zoho_sync_runs", column)

    op.drop_column("zoho_organizations", "remote_deleted_at")
    op.drop_column("zoho_organizations", "sync_version")
    op.drop_column("zoho_organizations", "sync_source")
    op.drop_index("ix_zoho_organizations_zoho_last_modified_time", table_name="zoho_organizations")
    op.drop_column("zoho_organizations", "zoho_last_modified_time")
    op.drop_column("zoho_organizations", "zoho_raw_synced_at")
    op.drop_column("zoho_organizations", "zoho_raw_hash")
    op.drop_constraint("zoho_organizations_public_id_key", "zoho_organizations", type_="unique")
    op.drop_column("zoho_organizations", "public_id")
