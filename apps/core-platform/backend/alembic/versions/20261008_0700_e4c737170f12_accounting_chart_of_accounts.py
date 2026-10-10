"""Accounting: chart of accounts, account assignments, and configurable resolution policies.

Creates schema ``accounting`` (docs/implementation-plan/accounts-module.md):

    account_types             GLOBAL  the 46-code type vocabulary — Zoho's documented list ∪ the
                                      tenant's own account-types response (Zoho numeric ids as
                                      ``zoho_id``); seeded from ``app/modules/accounting/seed_data.py``
    accounts                  ENTITY  one ledger account of one organization (Zoho crosswalk;
                                      ``zoho_id`` echo); composite same-organization parent FK
    account_purposes          GLOBAL  why an entity points at an account (seeded)
    account_purpose_policies  GLOBAL  which entity classes may carry which purposes
    account_assignments       ENTITY  polymorphic owner → account, per purpose (and currency)

and in ``core``:

    resolution_policies       ENTITY  tenant / organization overrides of the code-default
                                      resolution policies (app/modules/resolution)

Functions & triggers:

  * ``core.assert_owner_scope()`` — the owner shares the row's tenant, and its organization or
    is tenant-wide (an organization owns itself). Promoted from ``tax.assert_owner_scope``,
    which now delegates to it, so taxes and accounting share one rule;
  * ``accounting.derive_account_fields()`` — normal side from the type (inverted for a contra
    account), depth from the parent, cycle refusal;
  * ``accounting.cascade_account_depth()`` — re-parenting recomputes the subtree's depth (and
    bumps its ``row_version``: a Core update must, under ``RowVersionMixin``);
  * ``accounting.guard_account_delete()`` — no soft delete while children or assignments live;
  * ``accounting.check_account_assignment_integrity()`` (deferred) — owner exists, in scope,
    policy enabled, a currency only on a per-currency purpose, and — for LOCAL rows — the
    account's group / type fits the purpose (a source's rows are trusted; the service logs
    misfits);
  * ``accounting.find_orphan_account_assignments()`` — scheduled safety net.

Registrations: ``organization`` (every purpose, the end of every chain) and ``tax_component``
(output_tax / input_tax / tds_payable) as account owners; ``account`` as a commentable class.
Permissions: ``accounting.account:create|update|delete``, ``accounting.assignment:manage``,
``resolution.policy:manage``.

Downgrade drops everything created here and restores ``tax.assert_owner_scope``'s own body.
``core.entity_types`` rows stay (other modules may reference them; a registry row is harmless).

Revision ID: e4c737170f12
Revises: d81f4b6e2c90
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.accounting.registration import register_account_owner_type
from app.modules.accounting.seed_data import (
    ORGANIZATION_PURPOSES,
    TAX_COMPONENT_PURPOSES,
    account_type_rows,
    purpose_rows,
)
from app.modules.comments.registration import register_commentable_entity_type

revision: str = "e4c737170f12"
down_revision: str | None = "d81f4b6e2c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS accounting")

    op.create_table('account_purposes',
    sa.Column('code', sa.String(length=48), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('allowed_groups', postgresql.ARRAY(sa.String(length=16)), nullable=False, comment="The assigned account's group must be one of these"),
    sa.Column('allowed_types', postgresql.ARRAY(sa.String(length=64)), nullable=True, comment="Narrower rule: the account's type must be one of these; NULL = any of the groups"),
    sa.Column('per_currency', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='true = one account per (owner, purpose, currency) — AR/AP control accounts'),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("btrim(code) <> ''", name='ck_account_purposes_code_not_blank'),
    sa.CheckConstraint('cardinality(allowed_groups) > 0', name='ck_account_purposes_groups'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_account_purposes_code'),
    schema='accounting',
    comment='Why an entity points at an account (global vocabulary).'
    )
    op.create_index(op.f('ix_accounting_account_purposes_uuid'), 'account_purposes', ['uuid'], unique=True, schema='accounting')
    op.create_table('account_types',
    sa.Column('code', sa.String(length=64), nullable=False, comment="Zoho account_type, e.g. 'stock'"),
    sa.Column('zoho_id', sa.String(length=16), nullable=True, comment="Zoho's numeric account-type id ('1'..'112'), a vendor constant; NULL = never reported"),
    sa.Column('name', sa.Text(), nullable=False, comment='Zoho account_type_formatted'),
    sa.Column('account_group', sa.String(length=16), nullable=False, comment='asset/liability/equity/income/expense'),
    sa.Column('default_normal_balance_is_debit', sa.Boolean(), nullable=False, comment='true = debit-normal (asset, expense); drives accounts.normal_balance_is_debit'),
    sa.Column('is_sub_account_allowed', sa.Boolean(), nullable=True, comment='Zoho rule; NULL = not reported by Zoho (the service allows, Zoho decides on push)'),
    sa.Column('can_show_opening_balance', sa.Boolean(), nullable=True),
    sa.Column('can_enable_in_ze', sa.Boolean(), nullable=True, comment='Usable in Zoho Expense'),
    sa.Column('asset_type', sa.String(length=32), nullable=True, comment='fixed_asset / cwip / iaud'),
    sa.Column('is_documented', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment="In the Zoho API docs' allowed values (false = observed only in a tenant response)"),
    sa.Column('is_sales_eligible', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Offered by the sales picker'),
    sa.Column('is_purchase_eligible', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Offered by the purchase picker'),
    sa.Column('is_inventory_eligible', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Offered by the inventory picker'),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("account_group IN ('asset','liability','equity','income','expense')", name='ck_account_types_group'),
    sa.CheckConstraint("btrim(code) <> ''", name='ck_account_types_code_not_blank'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='uq_account_types_code'),
    schema='accounting',
    comment="Account type vocabulary (Zoho documented list ∪ the tenant's own response); global."
    )
    op.create_index(op.f('ix_accounting_account_types_uuid'), 'account_types', ['uuid'], unique=True, schema='accounting')
    op.create_index('uq_account_types_zoho_id', 'account_types', ['zoho_id'], unique=True, schema='accounting', postgresql_where=sa.text('zoho_id IS NOT NULL'))
    op.create_table('account_purpose_policies',
    sa.Column('entity_type_code', sa.String(length=64), nullable=False, comment='core.entity_types.code — the class must be registered first'),
    sa.Column('purpose_code', sa.String(length=48), nullable=False),
    sa.Column('falls_back_to_organization', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='When this owner carries nothing for the purpose, resolution asks the organization'),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='false = no NEW assignments for this class and purpose; existing rows stay valid'),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['entity_type_code'], ['core.entity_types.code'], name='fk_account_purpose_policies_entity_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['purpose_code'], ['accounting.account_purposes.code'], name='fk_account_purpose_policies_purpose', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('entity_type_code', 'purpose_code', name='uq_account_purpose_policies_class_purpose'),
    schema='accounting',
    comment='Which entity classes may carry which account purposes (global policy).'
    )
    op.create_index(op.f('ix_accounting_account_purpose_policies_uuid'), 'account_purpose_policies', ['uuid'], unique=True, schema='accounting')

    op.create_table('resolution_policies',
    sa.Column('facet', sa.String(length=32), nullable=False, comment='Registered facet code (tax, account)'),
    sa.Column('subject', sa.String(length=64), nullable=False, comment='Subject kind (sales_line, …)'),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='Ordered [{role, filter, on_unusable}] — validated against the registry'),
    sa.Column('use_organization_default', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='false = the organization default does not close the chain'),
    sa.Column('notes', sa.Text(), nullable=True, comment='Why this override exists (accountant sign-off, …)'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("btrim(facet) <> '' AND btrim(subject) <> ''", name='ck_resolution_policies_keys'),
    sa.CheckConstraint("jsonb_typeof(steps) = 'array'", name='ck_resolution_policies_steps_array'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_resolution_policies_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='core',
    comment='Tenant / organization overrides of the code-default resolution policies.'
    )
    op.create_index(op.f('ix_core_resolution_policies_deleted_at'), 'resolution_policies', ['deleted_at'], unique=False, schema='core')
    op.create_index(op.f('ix_core_resolution_policies_status'), 'resolution_policies', ['status'], unique=False, schema='core')
    op.create_index(op.f('ix_core_resolution_policies_tenant_id'), 'resolution_policies', ['tenant_id'], unique=False, schema='core')
    op.create_index(op.f('ix_core_resolution_policies_uuid'), 'resolution_policies', ['uuid'], unique=True, schema='core')
    op.create_index('ix_resolution_policies_tenant_org', 'resolution_policies', ['tenant_id', 'organization_id'], unique=False, schema='core')
    op.create_index('uq_resolution_policies_scope', 'resolution_policies', ['tenant_id', 'organization_id', 'facet', 'subject'], unique=True, schema='core', postgresql_nulls_not_distinct=True, postgresql_where=sa.text('deleted_at IS NULL'))

    op.create_table('accounts',
    sa.Column('account_type', sa.String(length=64), nullable=False, comment='accounting.account_types.code — an unknown Zoho type fails that one record'),
    sa.Column('parent_id', sa.BigInteger(), nullable=True, comment='Parent account (same organization); NULL = root'),
    sa.Column('account_code', sa.Text(), nullable=True, comment='Opaque GL code; leading zeros kept; blank = NULL'),
    sa.Column('account_name', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), sa.Computed("CASE WHEN account_code IS NULL THEN account_name ELSE account_code || ' - ' || account_name END", persisted=True), nullable=False, comment='code - name, for pickers and search (generated)'),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('currency_id', sa.BigInteger(), nullable=True, comment="currency.currencies; NULL = the organization's base currency"),
    sa.Column('is_contra', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment="Contra account: its normal side is the opposite of its type's (accumulated depreciation)"),
    sa.Column('normal_balance_is_debit', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='DERIVED by trigger from the type and is_contra — never written by the application'),
    sa.Column('depth', sa.SmallInteger(), server_default=sa.text('0'), nullable=False, comment="DERIVED by trigger: 0 for a root, parent's depth + 1; cascaded on re-parent"),
    sa.Column('is_system_account', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Zoho system account: cannot be deleted or re-typed'),
    sa.Column('is_user_created', sa.Boolean(), nullable=True, comment='Zoho is_user_created; NULL = not reported'),
    sa.Column('placeholder', sa.Text(), nullable=True, comment='Zoho template slug (gl_goods_in_transit): the robust key for recognising system accounts'),
    sa.Column('is_expense_claim_enabled', sa.Boolean(), nullable=True, comment='Zoho can_show_in_ze'),
    sa.Column('show_on_dashboard', sa.Boolean(), nullable=True),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Engine-maintained echo of Zoho account_id (not the identity of record)'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('verification_status', sa.String(length=20), server_default=sa.text("'unverified'"), nullable=False, comment='unverified / geocoded_only / field_verified / disputed (tables CHECK their own set)'),
    sa.Column('verification_method', sa.String(length=50), nullable=True, comment='How it was verified (geocode, field_visit, utility_bill, otp, …)'),
    sa.Column('verification_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Evidence: file refs, provider response ids, signatures'),
    sa.Column('verified_by', sa.BigInteger(), nullable=True, comment='users.id of the verifier (NULL = system)'),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True, comment='sha256 (hex) of the business payload — skip the write when unchanged'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("account_code IS NULL OR btrim(account_code) <> ''", name='ck_accounts_code_not_blank'),
    sa.CheckConstraint("btrim(account_name) <> ''", name='ck_accounts_name_not_blank'),
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_accounts_status'),
    sa.CheckConstraint('(parent_id IS NULL) = (depth = 0)', name='ck_accounts_depth_root'),
    sa.CheckConstraint('depth >= 0', name='ck_accounts_depth_nonneg'),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='ck_accounts_not_own_parent'),
    sa.ForeignKeyConstraint(['account_type'], ['accounting.account_types.code'], name='fk_accounts_account_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'currency_id'], ['currency.currencies.tenant_id', 'currency.currencies.id'], name='fk_accounts_currency', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'parent_id'], ['accounting.accounts.tenant_id', 'accounting.accounts.organization_id', 'accounting.accounts.id'], name='fk_accounts_parent_scope', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_accounts_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_accounts_tenant_id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_accounts_scope_id'),
    schema='accounting',
    comment='Chart of accounts: one ledger account of one organization; Zoho-synced (crosswalk).'
    )
    op.create_index(op.f('ix_accounting_accounts_deleted_at'), 'accounts', ['deleted_at'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_accounts_status'), 'accounts', ['status'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_accounts_tenant_id'), 'accounts', ['tenant_id'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_accounts_uuid'), 'accounts', ['uuid'], unique=True, schema='accounting')
    op.create_index(op.f('ix_accounting_accounts_verification_status'), 'accounts', ['verification_status'], unique=False, schema='accounting')
    op.create_index('ix_accounts_name_trgm', 'accounts', ['account_name'], unique=False, schema='accounting', postgresql_using='gin', postgresql_ops={'account_name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_accounts_org_type', 'accounts', ['organization_id', 'account_type'], unique=False, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_accounts_parent', 'accounts', ['parent_id'], unique=False, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_accounts_tenant_org', 'accounts', ['tenant_id', 'organization_id'], unique=False, schema='accounting')
    op.create_index('uq_accounts_code', 'accounts', ['organization_id', 'account_code'], unique=True, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL AND account_code IS NOT NULL'))
    op.create_index('uq_accounts_zoho_id', 'accounts', ['tenant_id', 'zoho_id'], unique=True, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('account_assignments',
    sa.Column('owner_type_code', sa.String(length=64), nullable=False, comment='core.entity_types.code of the owner, opted in per purpose'),
    sa.Column('owner_id', sa.BigInteger(), nullable=False, comment="The owner's internal id; no FK (polymorphic) — proved at COMMIT"),
    sa.Column('purpose_code', sa.String(length=48), nullable=False, comment='accounting.account_purposes.code'),
    sa.Column('account_id', sa.BigInteger(), nullable=True, comment="The account; NULL only while a source's account is pending"),
    sa.Column('currency_id', sa.BigInteger(), nullable=True, comment='Only for per-currency purposes; NULL = any / base currency'),
    sa.Column('external_ref', sa.Text(), nullable=True, comment="The source's id for the account while it is unresolved; the reconcile lane links it"),
    sa.Column('source_system', sa.String(length=32), nullable=True, comment="NULL = maintained locally; 'zoho' = fed by a sync (read-only through the API)"),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("source_system IS NULL OR btrim(source_system) <> ''", name='ck_account_assignments_source_not_blank'),
    sa.CheckConstraint('account_id IS NOT NULL OR (external_ref IS NOT NULL AND source_system IS NOT NULL)', name='ck_account_assignments_target'),
    sa.CheckConstraint('owner_id > 0', name='ck_account_assignments_owner_id'),
    sa.ForeignKeyConstraint(['owner_type_code', 'purpose_code'], ['accounting.account_purpose_policies.entity_type_code', 'accounting.account_purpose_policies.purpose_code'], name='fk_account_assignments_policy', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'currency_id'], ['currency.currencies.tenant_id', 'currency.currencies.id'], name='fk_account_assignments_currency', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'account_id'], ['accounting.accounts.tenant_id', 'accounting.accounts.organization_id', 'accounting.accounts.id'], name='fk_account_assignments_account', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_account_assignments_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='accounting',
    comment='Polymorphic account assignment: an owning entity → an account, for a purpose.'
    )
    op.create_index('ix_account_assignments_account', 'account_assignments', ['account_id'], unique=False, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL AND account_id IS NOT NULL'))
    op.create_index('ix_account_assignments_owner', 'account_assignments', ['owner_type_code', 'owner_id'], unique=False, schema='accounting', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_account_assignments_tenant_org', 'account_assignments', ['tenant_id', 'organization_id'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_account_assignments_deleted_at'), 'account_assignments', ['deleted_at'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_account_assignments_status'), 'account_assignments', ['status'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_account_assignments_tenant_id'), 'account_assignments', ['tenant_id'], unique=False, schema='accounting')
    op.create_index(op.f('ix_accounting_account_assignments_uuid'), 'account_assignments', ['uuid'], unique=True, schema='accounting')
    op.create_index('uq_account_assignments_slot', 'account_assignments', ['organization_id', 'owner_type_code', 'owner_id', 'purpose_code', 'currency_id'], unique=True, schema='accounting', postgresql_nulls_not_distinct=True, postgresql_where=sa.text('deleted_at IS NULL'))

    # ── the owner-scope rule, shared by every polymorphic-assignment module ──────
    # (promoted from tax.assert_owner_scope; an organization owns ITSELF)
    op.execute("""
        CREATE FUNCTION core.assert_owner_scope(p_type text, p_id bigint, p_tenant bigint, p_org bigint)
        RETURNS void
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            v_schema     text;
            v_table      text;
            v_rel        regclass;
            v_has_tenant boolean;
            v_has_org    boolean;
            v_tenant     bigint;
            v_org        bigint;
        BEGIN
            SELECT et.target_schema, et.target_table INTO v_schema, v_table
              FROM core.entity_types et
             WHERE et.code = p_type AND et.deleted_at IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'entity type % is not registered', p_type
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            v_rel := format('%I.%I', v_schema, v_table)::regclass;
            SELECT COALESCE(bool_or(a.attname = 'tenant_id'), false),
                   COALESCE(bool_or(a.attname = 'organization_id'), false)
              INTO v_has_tenant, v_has_org
              FROM pg_attribute a
             WHERE a.attrelid = v_rel AND a.attnum > 0 AND NOT a.attisdropped;
            IF (v_schema, v_table) = ('org_management', 'organizations') THEN
                v_has_org := false;                              -- read below as the row's own id
            END IF;
            IF NOT (v_has_tenant OR v_has_org) THEN
                RETURN;
            END IF;

            EXECUTE format('SELECT %s, %s FROM %s WHERE id = $1',
                           CASE WHEN v_has_tenant THEN 'tenant_id' ELSE 'NULL::bigint' END,
                           CASE WHEN v_has_org THEN 'organization_id'
                                WHEN (v_schema, v_table) = ('org_management', 'organizations') THEN 'id'
                                ELSE 'NULL::bigint' END,
                           v_rel)
               INTO v_tenant, v_org USING p_id;

            IF v_tenant IS NOT NULL AND v_tenant <> p_tenant THEN
                RAISE EXCEPTION '% % belongs to another tenant', p_type, p_id
                    USING ERRCODE = 'check_violation';
            END IF;
            -- An owner with no organization (tenant-wide) may carry any organization's row.
            IF v_org IS NOT NULL AND v_org <> p_org THEN
                RAISE EXCEPTION '% % belongs to organization %, not %', p_type, p_id, v_org, p_org
                    USING ERRCODE = 'check_violation';
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION tax.assert_owner_scope(p_type text, p_id bigint, p_tenant bigint, p_org bigint)
        RETURNS void
        LANGUAGE plpgsql STABLE AS $$
        BEGIN
            -- One rule for every polymorphic-assignment module: core.assert_owner_scope.
            PERFORM core.assert_owner_scope(p_type, p_id, p_tenant, p_org);
        END $$;
    """)

    # ── accounts: derived fields, cycle refusal, subtree depth, delete guard ─────
    op.execute("""
        CREATE FUNCTION accounting.derive_account_fields() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_default boolean;
            v_depth   smallint;
            v_cursor  bigint;
            v_steps   integer := 0;
        BEGIN
            SELECT t.default_normal_balance_is_debit INTO v_default
              FROM accounting.account_types t WHERE t.code = NEW.account_type;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'unknown account type %', NEW.account_type USING ERRCODE = 'foreign_key_violation';
            END IF;
            NEW.normal_balance_is_debit := v_default <> COALESCE(NEW.is_contra, false);

            IF NEW.parent_id IS NULL THEN
                NEW.depth := 0;
                RETURN NEW;
            END IF;
            IF NEW.parent_id = NEW.id THEN
                RAISE EXCEPTION 'account % cannot be its own parent', NEW.id USING ERRCODE = 'check_violation';
            END IF;

            -- FOR SHARE: a concurrent re-parent of the parent cannot interleave with this read.
            SELECT a.depth INTO v_depth FROM accounting.accounts a WHERE a.id = NEW.parent_id FOR SHARE;
            IF NOT FOUND THEN
                NEW.depth := 1;                 -- fk_accounts_parent_scope reports the missing parent
                RETURN NEW;
            END IF;
            NEW.depth := v_depth + 1;

            v_cursor := NEW.parent_id;
            WHILE v_cursor IS NOT NULL LOOP
                v_steps := v_steps + 1;
                IF v_steps > 64 THEN
                    RAISE EXCEPTION 'account hierarchy deeper than 64 levels (a cycle?)' USING ERRCODE = 'check_violation';
                END IF;
                IF v_cursor = NEW.id THEN
                    RAISE EXCEPTION 'account % would become its own ancestor (cycle)', NEW.id
                        USING ERRCODE = 'check_violation';
                END IF;
                SELECT a.parent_id INTO v_cursor FROM accounting.accounts a WHERE a.id = v_cursor;
            END LOOP;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_accounts_derive_fields
            BEFORE INSERT OR UPDATE OF parent_id, account_type, is_contra ON accounting.accounts
            FOR EACH ROW EXECUTE FUNCTION accounting.derive_account_fields();
    """)
    op.execute("""
        CREATE FUNCTION accounting.cascade_account_depth() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            WITH RECURSIVE subtree AS (
                SELECT a.id, NEW.depth + 1 AS d FROM accounting.accounts a WHERE a.parent_id = NEW.id
                UNION ALL
                SELECT a.id, s.d + 1 FROM accounting.accounts a JOIN subtree s ON a.parent_id = s.id WHERE s.d < 64
            )
            UPDATE accounting.accounts x
               SET depth = s.d, row_version = x.row_version + 1, updated_at = now()
              FROM subtree s
             WHERE x.id = s.id AND x.depth <> s.d;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_accounts_cascade_depth
            AFTER UPDATE OF parent_id ON accounting.accounts
            FOR EACH ROW WHEN (OLD.parent_id IS DISTINCT FROM NEW.parent_id)
            EXECUTE FUNCTION accounting.cascade_account_depth();
    """)
    op.execute("""
        CREATE FUNCTION accounting.guard_account_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM accounting.accounts c WHERE c.parent_id = OLD.id AND c.deleted_at IS NULL) THEN
                RAISE EXCEPTION 'account % still has live sub-accounts', OLD.id USING ERRCODE = 'foreign_key_violation';
            END IF;
            IF EXISTS (SELECT 1 FROM accounting.account_assignments x
                        WHERE x.account_id = OLD.id AND x.deleted_at IS NULL) THEN
                RAISE EXCEPTION 'account % is still assigned', OLD.id USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_accounts_guard_delete
            BEFORE UPDATE OF deleted_at ON accounting.accounts
            FOR EACH ROW WHEN (OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL)
            EXECUTE FUNCTION accounting.guard_account_delete();
    """)

    # ── assignments: integrity at COMMIT, orphan finder ───────────────────────────
    op.execute("""
        CREATE FUNCTION accounting.check_account_assignment_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_enabled      boolean;
            v_per_currency boolean;
            v_groups       text[];
            v_types        text[];
            v_group        text;
            v_type         text;
        BEGIN
            IF NEW.deleted_at IS NOT NULL THEN
                RETURN NULL;
            END IF;
            SELECT p.is_enabled INTO v_enabled
              FROM accounting.account_purpose_policies p
             WHERE p.entity_type_code = NEW.owner_type_code AND p.purpose_code = NEW.purpose_code;
            IF NOT COALESCE(v_enabled, false) THEN
                RAISE EXCEPTION 'account purpose % is disabled for entity type %', NEW.purpose_code, NEW.owner_type_code
                    USING ERRCODE = 'check_violation';
            END IF;

            PERFORM core.assert_entity_exists(NEW.owner_type_code, NEW.owner_id);
            PERFORM core.assert_owner_scope(NEW.owner_type_code, NEW.owner_id, NEW.tenant_id, NEW.organization_id);

            SELECT p.per_currency, p.allowed_groups::text[], p.allowed_types::text[]
              INTO v_per_currency, v_groups, v_types
              FROM accounting.account_purposes p WHERE p.code = NEW.purpose_code;
            IF NEW.currency_id IS NOT NULL AND NOT v_per_currency THEN
                RAISE EXCEPTION 'account purpose % is not per-currency', NEW.purpose_code
                    USING ERRCODE = 'check_violation';
            END IF;

            -- A source's rows are trusted (Zoho masters its own links); local rows are judged.
            IF NEW.account_id IS NOT NULL AND NEW.source_system IS NULL THEN
                SELECT t.account_group, a.account_type INTO v_group, v_type
                  FROM accounting.accounts a JOIN accounting.account_types t ON t.code = a.account_type
                 WHERE a.id = NEW.account_id;
                IF NOT (v_group = ANY (v_groups)) OR (v_types IS NOT NULL AND NOT (v_type = ANY (v_types))) THEN
                    RAISE EXCEPTION 'account % (% / %) does not fit purpose % (groups %, types %)',
                        NEW.account_id, v_group, v_type, NEW.purpose_code, v_groups, v_types
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_account_assignments_integrity
            AFTER INSERT OR UPDATE OF owner_type_code, owner_id, purpose_code, account_id, currency_id,
                source_system, tenant_id, organization_id, deleted_at
            ON accounting.account_assignments
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION accounting.check_account_assignment_integrity();
    """)
    op.execute("""
        CREATE FUNCTION accounting.find_orphan_account_assignments()
        RETURNS TABLE (assignment_id bigint, orphan_type text, orphan_id bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            r record;
        BEGIN
            FOR r IN SELECT et.code, et.target_schema, et.target_table
                       FROM core.entity_types et
                      WHERE et.deleted_at IS NULL
            LOOP
                RETURN QUERY EXECUTE format(
                    'SELECT a.id, a.owner_type_code::text, a.owner_id
                       FROM accounting.account_assignments a
                      WHERE a.owner_type_code = %L
                        AND a.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = a.owner_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)

    # ── seeds: the 46 account types, the purposes ──────────────────────────────
    types_table = sa.table(
        "account_types",
        *[sa.column(name) for name in (
            "code", "zoho_id", "name", "account_group", "default_normal_balance_is_debit",
            "is_sub_account_allowed", "can_show_opening_balance", "can_enable_in_ze", "asset_type",
            "is_documented", "is_sales_eligible", "is_purchase_eligible", "is_inventory_eligible", "sort_order",
            "created_by_name")],
        schema="accounting",
    )
    op.bulk_insert(types_table, [{**row, "created_by_name": "system:migration"} for row in account_type_rows()])
    purposes_table = sa.table(
        "account_purposes",
        sa.column("code"), sa.column("name"), sa.column("description"),
        sa.column("allowed_groups", postgresql.ARRAY(sa.String(16))),
        sa.column("allowed_types", postgresql.ARRAY(sa.String(64))),
        sa.column("per_currency"), sa.column("sort_order"), sa.column("created_by_name"),
        schema="accounting",
    )
    op.bulk_insert(purposes_table, [{**row, "created_by_name": "system:migration"} for row in purpose_rows()])

    # ── owners: the organization (end of every chain) and the tax component ─────
    bind = op.get_bind()
    register_account_owner_type(
        bind, code="organization", name="Organization", target_schema="org_management",
        target_table="organizations", purposes={purpose: False for purpose in ORGANIZATION_PURPOSES},
        description="Organization defaults — the last step of every account resolution.",
    )
    register_account_owner_type(
        bind, code="tax_component", name="Tax", target_schema="tax", target_table="tax_components",
        purposes={purpose: True for purpose in TAX_COMPONENT_PURPOSES},
        description="The ledger accounts a tax posts to (Zoho tax_account_id / purchase_tax_account_id / "
                    "tds_payable_account_id).",
    )
    register_commentable_entity_type(
        bind, code="account", name="Account", target_schema="accounting", target_table="accounts",
        description="Notes on a ledger account.",
    )

    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


_TAX_OWNER_SCOPE_BODY = """
    CREATE OR REPLACE FUNCTION tax.assert_owner_scope(p_type text, p_id bigint, p_tenant bigint, p_org bigint)
    RETURNS void
    LANGUAGE plpgsql STABLE AS $$
    DECLARE
        v_schema     text;
        v_table      text;
        v_rel        regclass;
        v_has_tenant boolean;
        v_has_org    boolean;
        v_tenant     bigint;
        v_org        bigint;
    BEGIN
        SELECT et.target_schema, et.target_table INTO v_schema, v_table
          FROM core.entity_types et
         WHERE et.code = p_type AND et.deleted_at IS NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'entity type % is not registered', p_type
                USING ERRCODE = 'foreign_key_violation';
        END IF;

        v_rel := format('%I.%I', v_schema, v_table)::regclass;
        SELECT COALESCE(bool_or(a.attname = 'tenant_id'), false),
               COALESCE(bool_or(a.attname = 'organization_id'), false)
          INTO v_has_tenant, v_has_org
          FROM pg_attribute a
         WHERE a.attrelid = v_rel AND a.attnum > 0 AND NOT a.attisdropped;
        IF NOT (v_has_tenant OR v_has_org) THEN
            RETURN;
        END IF;

        EXECUTE format('SELECT %s, %s FROM %s WHERE id = $1',
                       CASE WHEN v_has_tenant THEN 'tenant_id' ELSE 'NULL::bigint' END,
                       CASE WHEN v_has_org THEN 'organization_id' ELSE 'NULL::bigint' END,
                       v_rel)
           INTO v_tenant, v_org USING p_id;

        IF v_tenant IS NOT NULL AND v_tenant <> p_tenant THEN
            RAISE EXCEPTION '% % belongs to another tenant', p_type, p_id
                USING ERRCODE = 'check_violation';
        END IF;
        -- An owner with no organization (tenant-wide) may carry any organization's assignment.
        IF v_org IS NOT NULL AND v_org <> p_org THEN
            RAISE EXCEPTION '% % belongs to organization %, not %', p_type, p_id, v_org, p_org
                USING ERRCODE = 'check_violation';
        END IF;
    END $$;
"""


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM comments.commentable_entity_types WHERE entity_type_code = 'account'"))
    op.execute("DROP FUNCTION IF EXISTS accounting.find_orphan_account_assignments()")
    op.execute("DROP TRIGGER IF EXISTS ctrg_account_assignments_integrity ON accounting.account_assignments")
    op.execute("DROP FUNCTION IF EXISTS accounting.check_account_assignment_integrity()")
    op.execute("DROP TRIGGER IF EXISTS trg_accounts_guard_delete ON accounting.accounts")
    op.execute("DROP FUNCTION IF EXISTS accounting.guard_account_delete()")
    op.execute("DROP TRIGGER IF EXISTS trg_accounts_cascade_depth ON accounting.accounts")
    op.execute("DROP FUNCTION IF EXISTS accounting.cascade_account_depth()")
    op.execute("DROP TRIGGER IF EXISTS trg_accounts_derive_fields ON accounting.accounts")
    op.execute("DROP FUNCTION IF EXISTS accounting.derive_account_fields()")
    op.execute(_TAX_OWNER_SCOPE_BODY)
    op.execute("DROP FUNCTION IF EXISTS core.assert_owner_scope(text, bigint, bigint, bigint)")
    op.drop_table("account_assignments", schema="accounting")
    op.drop_table("accounts", schema="accounting")
    op.drop_table("resolution_policies", schema="core")
    op.drop_table("account_purpose_policies", schema="accounting")
    op.drop_table("account_types", schema="accounting")
    op.drop_table("account_purposes", schema="accounting")
    op.execute("DROP SCHEMA IF EXISTS accounting")
