"""Exchange rates: source identity + per-source uniqueness

Two sources may legitimately quote the same currency on the same day. Today's
partial unique ``(tenant, currency, effective_date)`` makes that impossible —
the second source would collide with the first and its rate would be lost.

  * ``rate_source`` joins the uniqueness key. It becomes NOT NULL DEFAULT
    'manual' first: a nullable column in a unique key defeats the constraint,
    because in Postgres NULLs are distinct, so every unsourced rate would be
    unique against every other one and duplicates would walk straight in.
  * ``external_source`` / ``external_id`` record which system produced a rate
    and what it calls it. Currency identity lives in the crosswalk
    (sync.sync_records); a rate is a child row with its own upstream id, so it
    carries its own echo rather than getting a crosswalk row of its own.

Additive and reversible. Existing rows are backfilled to 'manual', which is
what an unsourced rate in this table has always meant in practice.

Revision ID: d52a6f0bc318
Revises: c41e9b7d2f60
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d52a6f0bc318"
down_revision: str | None = "c41e9b7d2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "currency"
_TABLE = "exchange_rates"
_INDEX = "uq_exchange_rates_currency_date"
_LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(
        "external_source", sa.Text(), nullable=True,
        comment="Source system that produced this rate (zoho / sap / ...)",
    ), schema=_SCHEMA)
    op.add_column(_TABLE, sa.Column(
        "external_id", sa.Text(), nullable=True,
        comment="The source's id for this rate, verbatim (e.g. Zoho exchange_rate_id)",
    ), schema=_SCHEMA)

    # NOT NULL before the column joins a unique key (see the docstring).
    op.execute(f"UPDATE {_SCHEMA}.{_TABLE} SET rate_source = 'manual' WHERE rate_source IS NULL")
    op.alter_column(_TABLE, "rate_source", schema=_SCHEMA, nullable=False,
                    server_default=sa.text("'manual'"), existing_type=sa.Text())

    op.drop_index(_INDEX, table_name=_TABLE, schema=_SCHEMA)
    op.create_index(_INDEX, _TABLE,
                    ["tenant_id", "currency_id", "effective_date", "rate_source"],
                    unique=True, schema=_SCHEMA, postgresql_where=_LIVE)
    op.create_index("ix_exchange_rates_external", _TABLE,
                    ["tenant_id", "external_source", "external_id"],
                    unique=False, schema=_SCHEMA,
                    postgresql_where=sa.text("external_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_exchange_rates_external", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index(_INDEX, table_name=_TABLE, schema=_SCHEMA)
    # Narrowing the key back can collide if two sources already quoted one day;
    # keep the newest row per (tenant, currency, date) so the index can be built.
    op.execute(
        f"""
        DELETE FROM {_SCHEMA}.{_TABLE} a
        USING {_SCHEMA}.{_TABLE} b
        WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
          AND a.tenant_id = b.tenant_id AND a.currency_id = b.currency_id
          AND a.effective_date = b.effective_date AND a.id < b.id
        """
    )
    op.create_index(_INDEX, _TABLE, ["tenant_id", "currency_id", "effective_date"],
                    unique=True, schema=_SCHEMA, postgresql_where=_LIVE)
    op.alter_column(_TABLE, "rate_source", schema=_SCHEMA, nullable=True,
                    server_default=None, existing_type=sa.Text())
    op.drop_column(_TABLE, "external_id", schema=_SCHEMA)
    op.drop_column(_TABLE, "external_source", schema=_SCHEMA)
