"""Drop the zoho_currencies mirror

The last trace of the pre-crosswalk design. Currencies have written the
canonical ``currency.currencies`` since ``ef2c15ee5df8``/``b8d31c7f4a52``; the
mirror module was unregistered when the currencies adapter took over
``/settings/currencies`` (two modules cannot serve one endpoint), so this table
has had no writer since. Its identity moved to ``sync.sync_records`` and its
business columns to ``currency.currencies``.

Nothing is migrated out of it: it is unwritten and, on any environment that ran
the currencies sync, its contents are already in the canonical table keyed by
the same Zoho ids. The downgrade recreates the shape, not the data — there is no
honest way to rebuild a mirror's sync bookkeeping from the crosswalk, and
pretending otherwise would be worse than an empty table.

``zoho_locations`` and ``zoho_users`` are deliberately left: their modules are
still mirror modules and still write them. They go when those modules are
converted, one at a time, the way taxes was.

Revision ID: a9c7e412d83b
Revises: 83faf3dfb47d
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9c7e412d83b"
down_revision: str | None = "83faf3dfb47d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS zoho_currencies CASCADE")


def downgrade() -> None:
    op.create_table(
        "zoho_currencies",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("zoho_id", sa.String(length=50), nullable=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=True),
        sa.Column("currency_code", sa.String(length=100), nullable=True),
        sa.Column("currency_name", sa.String(length=255), nullable=True),
        sa.Column("currency_symbol", sa.String(length=16), nullable=True),
        sa.Column("currency_format", sa.String(length=100), nullable=True),
        sa.Column("price_precision", sa.Integer(), nullable=True),
        sa.Column("is_base_currency", sa.Boolean(), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        # the mirror bookkeeping this design replaced
        sa.Column("zoho_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("zoho_raw_hash", sa.LargeBinary(), nullable=True),
        sa.Column("zoho_raw_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zoho_last_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_source", sa.String(length=48), nullable=True),
        sa.Column("sync_version", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("custom_fields", postgresql.HSTORE(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_zoho_currencies_zoho_id_live", "zoho_currencies", ["tenant_id", "zoho_id"],
                    unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))
