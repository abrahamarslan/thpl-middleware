"""Parties: ``sales_channel`` — the one Zoho contact key the first audit found unmapped.

The data audit of the first live sync (THPL, 2026-10-09) compared every stored Zoho document with the tables
and found exactly one key no column, hub or deliberate exclusion accounted for: ``sales_channel`` (on every
contact; ``direct_sales``). It is not in Zoho's documented attributes, but it is a real commercial attribute
(route to market), so it becomes a column.

The value is backfilled from the crosswalk's stored document (``sync.sync_records.raw``) — zero Zoho calls,
and necessary because the apply gate skips unchanged contacts, so the next sync would never write it.

Revision ID: 5b8d2e71c4a9
Revises: 934e2e5ea8cb
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b8d2e71c4a9"
down_revision: str | None = "934e2e5ea8cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Also run after a sync that started before this migration (its rows were written without the column).
BACKFILL = """
    UPDATE party.parties p
       SET sales_channel = NULLIF(btrim(s.raw->>'sales_channel'), '')
      FROM sync.sync_records s
     WHERE s.module = 'parties' AND s.link_state = 'linked' AND s.entity_id = p.id
       AND p.sales_channel IS DISTINCT FROM NULLIF(btrim(s.raw->>'sales_channel'), '')
"""


def upgrade() -> None:
    op.add_column("parties", sa.Column(
        "sales_channel", sa.String(length=32), nullable=True,
        comment="Zoho sales_channel (route to market, e.g. direct_sales); no CHECK — Zoho's open set"),
        schema="party")
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column("parties", "sales_channel", schema="party")
