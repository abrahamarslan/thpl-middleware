"""Retention policies for sync.sync_payloads

The generalised retention job (app/modules/zoho/control/retention.py) maintains
every partitioned history table, but it only acts on a table that has policy
rows — "no policies" means "nothing to do". These seed the defaults for the
crosswalk's payload history.

Classes come from ``app.modules.sync.models.PAYLOAD_CLASS``:
``inserted``/``updated``/``resurrected`` → ``success``, ``tombstoned`` →
``failure``. Deletions are kept twice as long as ordinary changes because
"when did this record disappear, and what did it look like" is the question
that gets asked under audit.

These are only defaults: an operator changes retention by updating a row in
``zoho_retention_policies``, never by writing a migration.

Revision ID: c41e9b7d2f60
Revises: b8d31c7f4a52
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41e9b7d2f60"
down_revision: str | None = "b8d31c7f4a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "sync.sync_payloads"
_POLICIES = [
    {"table_name": _TABLE, "module": "*", "event_class": "*", "keep_days": 180},
    {"table_name": _TABLE, "module": "*", "event_class": "success", "keep_days": 180},
    {"table_name": _TABLE, "module": "*", "event_class": "failure", "keep_days": 365},
]


def upgrade() -> None:
    policies = sa.table(
        "zoho_retention_policies",
        sa.column("table_name", sa.String),
        sa.column("module", sa.String),
        sa.column("event_class", sa.String),
        sa.column("keep_days", sa.Integer),
        sa.column("archive", sa.String),
        sa.column("enabled", sa.Boolean),
    )
    op.bulk_insert(policies, [{**row, "archive": "none", "enabled": True} for row in _POLICIES])


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM zoho_retention_policies WHERE table_name = :t").bindparams(t=_TABLE)
    )
