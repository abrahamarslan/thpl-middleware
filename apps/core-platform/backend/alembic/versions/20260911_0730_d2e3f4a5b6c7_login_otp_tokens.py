"""login_otp_tokens — passwordless email OTP challenges

Revision ID: d2e3f4a5b6c7
Revises: b7c1f2a9d4e0
Create Date: 2026-09-11 07:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "b7c1f2a9d4e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_otp_tokens",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "code_hash",
            sa.String(length=255),
            nullable=False,
            comment="HMAC-SHA256 of the one-time code",
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("sent_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=45), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("email"),
    )
    op.create_index("ix_login_otp_tokens_expires_at", "login_otp_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_login_otp_tokens_expires_at", table_name="login_otp_tokens")
    op.drop_table("login_otp_tokens")
