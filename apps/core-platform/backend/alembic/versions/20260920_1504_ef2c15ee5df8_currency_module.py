"""Currency module — schema ``currency``: the canonical master + rate history.

Creates two tables:

    currency.currencies      one live currency per tenant + ISO code
    currency.exchange_rates  append-only, effective-dated rate history

Scoping is strict: ``organization_id`` is NOT NULL and the composite FK
``(tenant_id, organization_id)`` → ``org_management.organizations`` proves the
organization belongs to the same tenant. ``exchange_rates`` carries a composite
FK ``(tenant_id, currency_id)`` → ``currencies (tenant_id, id)`` so a rate can
never pair a currency with another tenant.

Additive and fully reversible: it creates a new schema and touches no existing
table. The unrelated drift Alembic autogenerate also reported (country_timezones
index shape, a password_reset_tokens comment, users.postal_code, and the
TimescaleDB-internal part_config tables) is deliberately NOT part of this
migration.

Revision ID: ef2c15ee5df8
Revises: 509eb251e3b3
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'ef2c15ee5df8'
down_revision = '509eb251e3b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS currency")

    op.create_table(
        'currencies',
        sa.Column('currency_id', sa.Text(), nullable=True, comment="L1 source echo of Zoho's currency_id"),
        sa.Column('zoho_id', sa.Text(), nullable=True, comment='L1 source echo of the Zoho Books id'),
        sa.Column('currency_code', sa.String(length=3), nullable=True,
                  comment='ISO 4217 alphabetic code (e.g. INR); NULL = unclassified'),
        sa.Column('currency_symbol', sa.Text(), nullable=True, comment="Display symbol, e.g. '₹', '$'"),
        sa.Column('currency_name', sa.Text(), nullable=True, comment="Canonical name, e.g. 'Indian Rupee'"),
        sa.Column('iso_numeric_code', sa.Text(), nullable=True, comment='ISO 4217 numeric code (3 digits), text'),
        sa.Column('country_code', sa.Text(), nullable=True, comment='ISO 3166 country code (L1 echo)'),
        sa.Column('kind', sa.Text(), server_default=sa.text("'fiat'"), nullable=True,
                  comment='fiat / crypto / metals / historical'),
        sa.Column('price_precision', sa.Integer(), server_default=sa.text('2'), nullable=True),
        sa.Column('decimal_separator', sa.String(length=1), server_default=sa.text("'.'"), nullable=True),
        sa.Column('thousand_separator', sa.String(length=1), server_default=sa.text("','"), nullable=True),
        sa.Column('symbol_placement', sa.Text(), server_default=sa.text("'before'"), nullable=True),
        sa.Column('space_between_symbol', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('secondary_grouping_size', sa.Integer(), server_default=sa.text('3'), nullable=True),
        sa.Column('currency_name_formatted', sa.Text(), nullable=True),
        sa.Column('currency_format', sa.Text(), nullable=True),
        sa.Column('currency_formatter', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('region_specific_formatting', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('use_regional_settings', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('is_default_currency', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('is_base_currency', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('allow_transactions', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('exchange_rate', sa.Numeric(precision=20, scale=10), server_default=sa.text('1.00'),
                  nullable=True, comment='CACHE of the latest rate; truth is currency.exchange_rates'),
        sa.Column('exchange_rate_as_of', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exchange_rate_last_updated', sa.DateTime(timezone=True), nullable=True),
        sa.Column('exchange_rate_source', sa.Text(), nullable=True),
        sa.Column('historical_rates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('auto_update_rate', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('auto_exchange_rate_enabled', sa.Boolean(), nullable=True),
        sa.Column('rate_update_frequency', sa.Text(), nullable=True),
        sa.Column('rounding_method', sa.Text(), server_default=sa.text("'round'"), nullable=True),
        sa.Column('rounding_precision', sa.Integer(), server_default=sa.text('2'), nullable=True),
        sa.Column('apply_rounding_to_total_only', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('effective_date_formatted', sa.Text(), nullable=True),
        sa.Column('last_api_sync', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gl_account_code', sa.Text(), nullable=True),
        sa.Column('require_exchange_rate_entry', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('allow_override_rate', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('rate_fluctuation_threshold', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('risk_management_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('requires_authorization', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('uuid', sa.UUID(), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
        sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant'),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('created_by_name', sa.String(length=255), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('updated_by_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('app_version', sa.String(length=32), nullable=True),
        sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('verification_status', sa.String(length=20), server_default=sa.text("'unverified'"), nullable=False),
        sa.Column('verification_method', sa.String(length=50), nullable=True),
        sa.Column('verification_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('verified_by', sa.BigInteger(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivation_reason', sa.Text(), nullable=True),
        sa.Column('deactivated_by', sa.BigInteger(), nullable=True),
        sa.Column('owner_type', sa.String(length=50), nullable=False),
        sa.Column('owner_id', sa.BigInteger(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.BigInteger(), nullable=True),
        sa.Column('deleted_reason', sa.Text(), nullable=True),
        sa.CheckConstraint("currency_formatter IS NULL OR jsonb_typeof(currency_formatter) = 'object'",
                           name='chk_currency_formatter_object'),
        sa.CheckConstraint("kind IS DISTINCT FROM 'fiat' OR currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
                           name='chk_currency_code_iso4217'),
        sa.CheckConstraint("kind IS NULL OR kind IN ('fiat','crypto','metals','historical')",
                           name='chk_currency_kind'),
        sa.CheckConstraint("owner_type IN ('tenant','organization','connection','system')",
                           name='chk_currency_owner_type'),
        sa.CheckConstraint(
            "rate_update_frequency IS NULL OR rate_update_frequency IN ('hourly','daily','weekly','manual')",
            name='chk_currency_rate_update_frequency'),
        sa.CheckConstraint(
            "region_specific_formatting IS NULL OR jsonb_typeof(region_specific_formatting) = 'object'",
            name='chk_currency_region_formatting_object'),
        sa.CheckConstraint("risk_management_rules IS NULL OR jsonb_typeof(risk_management_rules) = 'object'",
                           name='chk_currency_risk_rules_object'),
        sa.CheckConstraint("rounding_method IS NULL OR rounding_method IN ('round','ceil','floor')",
                           name='chk_currency_rounding_method'),
        sa.CheckConstraint("status IN ('active','inactive','archived')", name='chk_currency_status'),
        sa.CheckConstraint("symbol_placement IS NULL OR symbol_placement IN ('before','after')",
                           name='chk_currency_symbol_placement'),
        sa.CheckConstraint("verification_status IN ('unverified','pending','verified','rejected')",
                           name='chk_currency_verification_status'),
        sa.CheckConstraint('exchange_rate IS NULL OR exchange_rate >= 0', name='chk_currency_exchange_rate'),
        sa.CheckConstraint('price_precision IS NULL OR price_precision >= 0', name='chk_currency_price_precision'),
        sa.CheckConstraint('rate_fluctuation_threshold IS NULL OR rate_fluctuation_threshold >= 0',
                           name='chk_currency_fluctuation_threshold'),
        sa.CheckConstraint('rounding_precision IS NULL OR rounding_precision >= 0',
                           name='chk_currency_rounding_precision'),
        sa.ForeignKeyConstraint(['tenant_id', 'organization_id'],
                                ['org_management.organizations.tenant_id', 'org_management.organizations.id'],
                                name='fk_currencies_tenant_org', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_currencies_tenant_id'),
        schema='currency',
        comment='Canonical currency master (one live row per tenant + currency code).',
    )
    op.create_index('ix_currencies_kind_active', 'currencies', ['tenant_id', 'kind', 'is_active'], unique=False,
                    schema='currency', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_currencies_owner', 'currencies', ['tenant_id', 'owner_type', 'owner_id'], unique=False,
                    schema='currency', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_currencies_tenant_org', 'currencies', ['tenant_id', 'organization_id'], unique=False,
                    schema='currency')
    op.create_index('ix_currency_currencies_deleted_at', 'currencies', ['deleted_at'], unique=False, schema='currency')
    op.create_index('ix_currency_currencies_status', 'currencies', ['status'], unique=False, schema='currency')
    op.create_index('ix_currency_currencies_tenant_id', 'currencies', ['tenant_id'], unique=False, schema='currency')
    op.create_index('ix_currency_currencies_uuid', 'currencies', ['uuid'], unique=True, schema='currency')
    op.create_index('ix_currency_currencies_verification_status', 'currencies', ['verification_status'],
                    unique=False, schema='currency')
    op.create_index('uq_currencies_one_base', 'currencies', ['tenant_id', 'organization_id'], unique=True,
                    schema='currency', postgresql_where=sa.text('is_base_currency AND deleted_at IS NULL'))
    op.create_index('uq_currencies_one_default', 'currencies', ['tenant_id', 'organization_id'], unique=True,
                    schema='currency', postgresql_where=sa.text('is_default_currency AND deleted_at IS NULL'))
    op.create_index('uq_currencies_tenant_code', 'currencies', ['tenant_id', 'currency_code'], unique=True,
                    schema='currency',
                    postgresql_where=sa.text('deleted_at IS NULL AND currency_code IS NOT NULL'))

    op.create_table(
        'exchange_rates',
        sa.Column('zoho_id', sa.Text(), nullable=True),
        sa.Column('currency_id', sa.BigInteger(), nullable=False, comment='Owning currency (composite tenant FK)'),
        sa.Column('rate', sa.Numeric(precision=15, scale=6), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('rate_source', sa.Text(), nullable=True),
        sa.Column('rate_type', sa.Text(), nullable=True),
        sa.Column('uuid', sa.UUID(), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
        sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant'),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.Column('created_by_name', sa.String(length=255), nullable=True),
        sa.Column('updated_by', sa.BigInteger(), nullable=True),
        sa.Column('updated_by_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('app_version', sa.String(length=32), nullable=True),
        sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('verification_status', sa.String(length=20), server_default=sa.text("'unverified'"), nullable=False),
        sa.Column('verification_method', sa.String(length=50), nullable=True),
        sa.Column('verification_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('verified_by', sa.BigInteger(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivation_reason', sa.Text(), nullable=True),
        sa.Column('deactivated_by', sa.BigInteger(), nullable=True),
        sa.Column('owner_type', sa.String(length=50), nullable=False),
        sa.Column('owner_id', sa.BigInteger(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by', sa.BigInteger(), nullable=True),
        sa.Column('deleted_reason', sa.Text(), nullable=True),
        sa.CheckConstraint("owner_type IN ('tenant','organization','connection','system')",
                           name='chk_exchange_rate_owner_type'),
        sa.CheckConstraint("status IN ('active','superseded','invalid','archived')", name='chk_exchange_rate_status'),
        sa.CheckConstraint("sync_metadata IS NULL OR jsonb_typeof(sync_metadata) = 'object'",
                           name='chk_exchange_rate_sync_metadata_object'),
        sa.CheckConstraint("verification_status IN ('unverified','pending','verified','rejected')",
                           name='chk_exchange_rate_verification_status'),
        sa.CheckConstraint('rate >= 0', name='chk_exchange_rate_nonnegative'),
        sa.ForeignKeyConstraint(['tenant_id', 'currency_id'],
                                ['currency.currencies.tenant_id', 'currency.currencies.id'],
                                name='fk_exchange_rates_currency', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id', 'organization_id'],
                                ['org_management.organizations.tenant_id', 'org_management.organizations.id'],
                                name='fk_exchange_rates_tenant_org', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_exchange_rates_tenant_id'),
        schema='currency',
        comment='Append-only, effective-dated exchange-rate history.',
    )
    op.create_index('ix_currency_exchange_rates_deleted_at', 'exchange_rates', ['deleted_at'], unique=False,
                    schema='currency')
    op.create_index('ix_currency_exchange_rates_status', 'exchange_rates', ['status'], unique=False, schema='currency')
    op.create_index('ix_currency_exchange_rates_tenant_id', 'exchange_rates', ['tenant_id'], unique=False,
                    schema='currency')
    op.create_index('ix_currency_exchange_rates_uuid', 'exchange_rates', ['uuid'], unique=True, schema='currency')
    op.create_index('ix_currency_exchange_rates_verification_status', 'exchange_rates', ['verification_status'],
                    unique=False, schema='currency')
    op.create_index('ix_exchange_rates_currency_date', 'exchange_rates', ['currency_id', 'effective_date'],
                    unique=False, schema='currency', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_exchange_rates_owner', 'exchange_rates', ['tenant_id', 'owner_type', 'owner_id'],
                    unique=False, schema='currency', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_exchange_rates_tenant_org', 'exchange_rates', ['tenant_id', 'organization_id'],
                    unique=False, schema='currency')
    op.create_index('uq_exchange_rates_currency_date', 'exchange_rates',
                    ['tenant_id', 'currency_id', 'effective_date'], unique=True, schema='currency',
                    postgresql_where=sa.text('deleted_at IS NULL'))


def downgrade() -> None:
    op.drop_index('uq_exchange_rates_currency_date', table_name='exchange_rates', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_exchange_rates_tenant_org', table_name='exchange_rates', schema='currency')
    op.drop_index('ix_exchange_rates_owner', table_name='exchange_rates', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_exchange_rates_currency_date', table_name='exchange_rates', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_currency_exchange_rates_verification_status', table_name='exchange_rates', schema='currency')
    op.drop_index('ix_currency_exchange_rates_uuid', table_name='exchange_rates', schema='currency')
    op.drop_index('ix_currency_exchange_rates_tenant_id', table_name='exchange_rates', schema='currency')
    op.drop_index('ix_currency_exchange_rates_status', table_name='exchange_rates', schema='currency')
    op.drop_index('ix_currency_exchange_rates_deleted_at', table_name='exchange_rates', schema='currency')
    op.drop_table('exchange_rates', schema='currency')

    op.drop_index('uq_currencies_tenant_code', table_name='currencies', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL AND currency_code IS NOT NULL'))
    op.drop_index('uq_currencies_one_default', table_name='currencies', schema='currency',
                  postgresql_where=sa.text('is_default_currency AND deleted_at IS NULL'))
    op.drop_index('uq_currencies_one_base', table_name='currencies', schema='currency',
                  postgresql_where=sa.text('is_base_currency AND deleted_at IS NULL'))
    op.drop_index('ix_currency_currencies_verification_status', table_name='currencies', schema='currency')
    op.drop_index('ix_currency_currencies_uuid', table_name='currencies', schema='currency')
    op.drop_index('ix_currency_currencies_tenant_id', table_name='currencies', schema='currency')
    op.drop_index('ix_currency_currencies_status', table_name='currencies', schema='currency')
    op.drop_index('ix_currency_currencies_deleted_at', table_name='currencies', schema='currency')
    op.drop_index('ix_currencies_tenant_org', table_name='currencies', schema='currency')
    op.drop_index('ix_currencies_owner', table_name='currencies', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_currencies_kind_active', table_name='currencies', schema='currency',
                  postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('currencies', schema='currency')

    op.execute("DROP SCHEMA IF EXISTS currency")