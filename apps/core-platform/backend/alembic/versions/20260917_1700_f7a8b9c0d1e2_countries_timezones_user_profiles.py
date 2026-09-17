"""countries, timezones, country_timezones, and user_profiles tables

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-17 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Reference table: countries (ISO 3166-1)
    op.create_table(
        "countries",
        sa.Column("iso2", sa.String(length=2), nullable=False),
        sa.Column("iso3", sa.String(length=3), nullable=False),
        sa.Column("numeric_code", sa.String(length=3), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("official_name", sa.String(length=300), nullable=True),
        sa.Column("region", sa.String(length=75), nullable=True),
        sa.Column("subregion", sa.String(length=75), nullable=True),
        sa.Column("phone_code", sa.String(length=10), nullable=True),
        sa.Column("currency_code", sa.String(length=5), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("iso2"),
        sa.UniqueConstraint("iso3"),
    )

    # 2. Reference table: timezones (IANA tz database identifiers)
    op.create_table(
        "timezones",
        sa.Column("iana_name", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("iana_name"),
    )

    # 3. Mapping table: country_timezones (multi-zone countries)
    op.create_table(
        "country_timezones",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("country_iso2", sa.String(length=2), nullable=False),
        sa.Column("timezone_name", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["country_iso2"], ["countries.iso2"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timezone_name"], ["timezones.iana_name"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_iso2", "timezone_name", name="uq_country_timezone"),
    )
    # Exactly one default timezone per country
    op.create_index(
        "uq_country_default_tz",
        "country_timezones",
        ["country_iso2"],
        unique=True,
        postgresql_where=sa.text("is_default = TRUE"),
    )

    # 4. User profile: user_profiles (BigInt PK + UUID public key + auto-unless-overridden)
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("country_iso2", sa.String(length=2), nullable=True),
        sa.Column("timezone_name", sa.String(length=64), nullable=True),
        sa.Column("timezone_source", sa.String(length=10), nullable=False, server_default="auto"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("timezone_source IN ('auto', 'manual')", name="ck_user_profiles_tz_source"),
        sa.ForeignKeyConstraint(["country_iso2"], ["countries.iso2"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["timezone_name"], ["timezones.iana_name"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )
    op.create_index("idx_user_profiles_country", "user_profiles", ["country_iso2"], unique=False)
    op.create_index("ix_user_profiles_uuid", "user_profiles", ["uuid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_profiles_uuid", table_name="user_profiles")
    op.drop_index("idx_user_profiles_country", table_name="user_profiles")
    op.drop_table("user_profiles")

    op.drop_index("uq_country_default_tz", table_name="country_timezones")
    op.drop_table("country_timezones")

    op.drop_table("timezones")
    op.drop_table("countries")
