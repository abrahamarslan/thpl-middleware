"""Brands — add the Zoho identity echo

``core.brands`` gains one column: ``zoho_id`` (Text, echo of Zoho's ``brand_id``,
written by the sync engine — never by hand, never matched on). This is the
same shape as `core.categories.zoho_id` / `currency.currencies.zoho_id`: the
crosswalk (``sync.sync_records``) is the identity of record; the echo exists
because "is this brand Zoho-linked?" is asked on every local edit and should
not need a join.

Reverses ``Brand``'s original design ("not a Zoho mirror") — a deliberate
decision, made on the user's explicit instruction once Zoho's real but
undocumented ``/brands`` endpoint was confirmed live.
See ``docs/implementation-plan/brands-zoho-sync.md``.

Revision ID: 999509053c9f
Revises: 807ccba816ef
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "999509053c9f"
down_revision: str | None = "807ccba816ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brands",
        sa.Column("zoho_id", sa.Text(), nullable=True,
                  comment="Echo of Zoho's brand_id, written by the sync engine; "
                          "identity of record is sync.sync_records"),
        schema="core",
    )
    op.create_index("ix_brands_zoho_id", "brands", ["zoho_id"], unique=False, schema="core")
    op.create_index("uq_brands_zoho_id_live", "brands", ["zoho_id"], unique=True, schema="core",
                    postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_brands_zoho_id_live", table_name="brands", schema="core")
    op.drop_index("ix_brands_zoho_id", table_name="brands", schema="core")
    op.drop_column("brands", "zoho_id", schema="core")
