"""user_location_pings: the DEFAULT partition, without which the table is unwritable

``fdbf62102e86`` created ``user_location_pings`` as a RANGE-partitioned parent on
``recorded_at`` and no partitions. A partitioned parent with no matching partition
rejects every INSERT ("no partition of relation ... found for row"), so the whole
location-history path was dead on arrival — on the scratch DB, in CI, and in
production alike.

A DEFAULT partition is the fix, and the right one:

  * Postgres routes any row matching no other partition into it, so a ping is
    never lost no matter what the device clock says (offline queues replay fixes
    that are hours or days old, and a stale clock must not drop data);
  * pg_partman can take over afterwards — it creates the monthly partitions and
    moves the default's rows into them (``partman.partition_data_proc``). It is
    installed and preloaded on the deployment image, but NOT on the scratch test
    Postgres, so the table must be correct without it. That is exactly what a
    default partition guarantees.

The table comment keeps saying "monthly partitions via pg_partman": that remains
the operating plan. This migration makes the table work before, during and after
that registration, instead of depending on it.

Revision ID: 3b7f0ae91c46
Revises: 9c1e2f3a4b5c
Create Date: 2026-09-22 14:00:00.000000
"""
from alembic import op

revision = '3b7f0ae91c46'
down_revision = '9c1e2f3a4b5c'
branch_labels = None
depends_on = None

_DEFAULT_PARTITION = "user_location_pings_default"


def upgrade() -> None:
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {_DEFAULT_PARTITION} "
        "PARTITION OF user_location_pings DEFAULT"
    )
    op.execute(
        f"COMMENT ON TABLE {_DEFAULT_PARTITION} IS "
        "'Catch-all partition: holds fixes outside every monthly partition "
        "(late offline replays, skewed device clocks). pg_partman drains it.'"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_DEFAULT_PARTITION}")
