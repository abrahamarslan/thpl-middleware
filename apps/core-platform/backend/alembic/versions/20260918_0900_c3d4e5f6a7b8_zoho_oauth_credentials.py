"""zoho_oauth_credentials — encrypted refresh-token storage

Replaces storing the Zoho refresh token in the hierarchical settings module,
whose audit log kept every value (including the secret) in plaintext forever.
The token is encrypted with pgcrypto ``pgp_sym_encrypt``; the key lives only
in the environment (``ZOHO_TOKEN_ENCRYPTION_KEY``).

The data migration deliberately does NOT copy the old value across: the
plaintext rows are deleted instead, and the integration is reconnected once
(/api/zoho/auth/initiate) so the secret is rotated rather than migrated.

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto is in POSTGRES_MULTIPLE_EXTENSIONS, but extensions are created on
    # first cluster init only — make the migration self-sufficient.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "zoho_oauth_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column(
            "refresh_token_enc",
            sa.LargeBinary(),
            nullable=True,
            comment="pgp_sym_encrypt(refresh_token, ZOHO_TOKEN_ENCRYPTION_KEY)",
        ),
        sa.Column(
            "api_domain",
            sa.String(length=255),
            nullable=True,
            comment="api_domain returned by Zoho; validated against the configured base URLs",
        ),
        sa.Column("scope", sa.String(length=1024), nullable=True),
        sa.Column("credential_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "rotated_by",
            sa.BigInteger(),
            nullable=True,
            comment="users.id of the operator who reconnected",
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_zoho_oauth_credentials_org_id"), "zoho_oauth_credentials", ["org_id"], unique=True
    )

    # Purge any refresh token the v1 code persisted through the settings module,
    # including its audit trail. The secret is rotated, not migrated.
    # Guarded with to_regclass: the settings tables are created by a later
    # migration in some environments, and this one must still apply.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.setting_audit_logs') IS NOT NULL THEN
                DELETE FROM setting_audit_logs
                WHERE definition_key IN ('zoho_refresh_token', 'zoho.oauth.refresh_token');
            END IF;
            IF to_regclass('public.setting_values') IS NOT NULL
               AND to_regclass('public.setting_definitions') IS NOT NULL THEN
                DELETE FROM setting_values
                WHERE definition_id IN (
                    SELECT id FROM setting_definitions
                    WHERE key IN ('zoho_refresh_token', 'zoho.oauth.refresh_token')
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_zoho_oauth_credentials_org_id"), table_name="zoho_oauth_credentials")
    op.drop_table("zoho_oauth_credentials")
