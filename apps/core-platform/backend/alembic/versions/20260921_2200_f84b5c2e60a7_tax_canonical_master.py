"""Tax canonical master — schema ``tax``, replacing the zoho_taxes mirror

Taxes join currencies and organizations on the crosswalk architecture: a
canonical ``tax.taxes`` holding business columns and one maintained ``zoho_id``
echo, with identity, raw payload and gate state in ``sync.sync_records``.

Field coverage is complete against docs/zoho-docs-md/taxes.md, including the
edition-specific attributes the old mirror had no column for
(``tds_payable_account_id`` — Mexico; ``purchase_tax_expense_account_id`` —
Australia/Canada). Those arrived from Zoho and were silently dropped.

``zoho_taxes`` is dropped rather than left behind: unlike currencies it has no
canonical twin to backfill from, and the sync now writes ``tax.taxes``. Its
data is reproduced by one sync run.

Revision ID: f84b5c2e60a7
Revises: e73c4a1d9f25
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f84b5c2e60a7"
down_revision: str | None = "e73c4a1d9f25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "tax"
_LIVE_ZOHO = sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL")
_LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")

    op.create_table(
        "taxes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("uuid", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("zoho_id", sa.String(length=50), nullable=True,
                  comment="Zoho tax_id, echoed by the engine; never matched on"),
        sa.Column("tax_name", sa.String(length=255), nullable=True, comment="Name of the tax"),
        sa.Column("tax_percentage", sa.Numeric(precision=9, scale=4), nullable=True,
                  comment="Percentage taxable; Decimal, never float-parsed"),
        sa.Column("tax_type", sa.String(length=32), nullable=True, comment="tax | compound_tax"),
        sa.Column("tax_specific_type", sa.String(length=32), nullable=True),
        sa.Column("tax_factor", sa.String(length=16), nullable=True, comment="(Mexico) rate | share"),
        sa.Column("tax_authority_id", sa.String(length=50), nullable=True),
        sa.Column("tax_authority_name", sa.String(length=255), nullable=True),
        sa.Column("is_value_added", sa.Boolean(), nullable=True, comment="VAT-style tax"),
        sa.Column("is_default_tax", sa.Boolean(), nullable=True),
        sa.Column("is_editable", sa.Boolean(), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("tax_account_id", sa.String(length=50), nullable=True),
        sa.Column("purchase_tax_account_id", sa.String(length=50), nullable=True),
        sa.Column("output_tax_account_name", sa.String(length=255), nullable=True),
        sa.Column("purchase_tax_account_name", sa.String(length=255), nullable=True),
        sa.Column("tds_payable_account_id", sa.String(length=50), nullable=True,
                  comment="(Mexico) input-tax account charged on purchases"),
        sa.Column("purchase_tax_expense_account_id", sa.BigInteger(), nullable=True,
                  comment="(Australia, Canada) account purchase tax is computed in"),
        sa.Column("notes", sa.Text(), nullable=True,
                  comment="Operator notes; never written by a sync"),
        # TenantEntityMixin
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_by_name", sa.String(length=160), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_name", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        # DeactivationMixin
        sa.Column("deactivation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("deactivated_by", sa.BigInteger(), nullable=True),
        # SoftDeleteFilteredMixin
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id",
                                 "org_management.organizations.id"],
                                name="fk_taxes_tenant_org", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
        comment="Canonical tax master (rates, authorities, accounts).",
    )

    op.create_index("uq_taxes_zoho_id_live", "taxes", ["tenant_id", "zoho_id"], unique=True,
                    schema=_SCHEMA, postgresql_where=_LIVE_ZOHO)
    op.create_index("ix_taxes_tenant_name", "taxes", ["tenant_id", "tax_name"], unique=False,
                    schema=_SCHEMA, postgresql_where=_LIVE)
    op.create_index("ix_taxes_specific_type", "taxes", ["tenant_id", "tax_specific_type"],
                    unique=False, schema=_SCHEMA, postgresql_where=_LIVE)
    op.create_index("ix_taxes_tenant_org", "taxes", ["tenant_id", "organization_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_tax_taxes_deleted_at", "taxes", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_tax_taxes_status", "taxes", ["status"], unique=False, schema=_SCHEMA)
    op.create_index("ix_tax_taxes_tenant_id", "taxes", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index("ix_tax_taxes_uuid", "taxes", ["uuid"], unique=True, schema=_SCHEMA)
    op.create_index("ix_tax_taxes_zoho_id", "taxes", ["zoho_id"], unique=False, schema=_SCHEMA)

    op.execute("DROP TABLE IF EXISTS zoho_taxes CASCADE")


def downgrade() -> None:
    op.create_table(
        "zoho_taxes",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("zoho_id", sa.String(length=50), nullable=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=True),
        sa.Column("tax_name", sa.String(length=255), nullable=True),
        sa.Column("tax_percentage", sa.Numeric(precision=9, scale=4), nullable=True),
        sa.Column("tax_type", sa.String(length=32), nullable=True),
        sa.Column("tax_specific_type", sa.String(length=32), nullable=True),
        sa.Column("tax_factor", sa.String(length=16), nullable=True),
        sa.Column("tax_authority_id", sa.String(length=50), nullable=True),
        sa.Column("tax_authority_name", sa.String(length=255), nullable=True),
        sa.Column("is_value_added", sa.Boolean(), nullable=True),
        sa.Column("is_default_tax", sa.Boolean(), nullable=True),
        sa.Column("is_editable", sa.Boolean(), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("tax_account_id", sa.String(length=50), nullable=True),
        sa.Column("purchase_tax_account_id", sa.String(length=50), nullable=True),
        sa.Column("output_tax_account_name", sa.String(length=255), nullable=True),
        sa.Column("purchase_tax_account_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_table("taxes", schema=_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} RESTRICT")
