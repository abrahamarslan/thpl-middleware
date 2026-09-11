"""users moderation: ban & throttle columns

Revision ID: e5f6a7b8c9d0
Revises: d2e3f4a5b6c7
Create Date: 2026-09-11 09:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


_COLUMNS = (
    sa.Column("is_banned", sa.Boolean(), nullable=True, comment="Hard ban: cannot authenticate or use the API"),
    sa.Column("ban_reason", sa.Text(), nullable=True, comment="Why the account was banned"),
    sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True, comment="When the ban was applied"),
    sa.Column("banned_until", sa.DateTime(timezone=True), nullable=True, comment="Ban expiry (NULL = permanent)"),
    sa.Column("banned_by", sa.BigInteger(), nullable=True, comment="Actor user id that applied the ban"),
    sa.Column("is_throttled", sa.Boolean(), nullable=True, comment="Soft restriction: new auth attempts are rate-limited"),
    sa.Column("throttle_reason", sa.Text(), nullable=True, comment="Why the account was throttled"),
    sa.Column("throttled_at", sa.DateTime(timezone=True), nullable=True, comment="When the throttle was applied"),
    sa.Column("throttled_until", sa.DateTime(timezone=True), nullable=True, comment="Throttle expiry (NULL = until lifted)"),
    sa.Column("throttled_by", sa.BigInteger(), nullable=True, comment="Actor user id that applied the throttle"),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("users", column)
    op.create_index("ix_users_is_banned", "users", ["is_banned"], unique=False)
    op.create_index("ix_users_is_throttled", "users", ["is_throttled"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_is_throttled", table_name="users")
    op.drop_index("ix_users_is_banned", table_name="users")
    for column in reversed(_COLUMNS):
        op.drop_column("users", column.name)
