"""add country_code to users table

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-09-17 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "country_code",
            sa.String(length=2),
            nullable=True,
            comment="ISO 3166-1 alpha-2 country code (e.g. IN, US)",
        ),
    )
    op.create_index("ix_users_country_code", "users", ["country_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_country_code", table_name="users")
    op.drop_column("users", "country_code")
