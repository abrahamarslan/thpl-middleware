"""Pricing: Zoho price lists (pricebooks), their items and volume brackets — organization-scoped.

    pricing.pricebooks               one price list of one organization (Zoho crosswalk module ``pricebooks``)
    pricing.pricebook_items          an item's entry in a per_item book (unit rate, or the parent of brackets)
    pricing.pricebook_item_brackets  one quantity bracket of a volume book's item

Every table is ``OrgEntityMixin`` (tenant + organization NOT NULL); children pin their parent's tenant
AND organization through composite FKs. Items reference Zoho's ``item_id`` as text until an items
module exists. Rows arrive from the Zoho sync (``app/modules/pricebooks/zoho``); nothing is seeded —
the books land in the organization the Zoho connection belongs to (THPL by default).

Downgrade drops the three tables and the schema (the crosswalk rows of module ``pricebooks`` in
``sync.sync_records`` are left; a re-upgrade + FULL sync re-adopts them).

**Renamed** to price lists (``pricing.price_lists`` …, module ``price_lists``, package
``app/modules/price_lists``) by the next revision, ``7c3e91a05d24``; this one is kept as written so the
chain replays exactly what dev ran.

Revision ID: 02b470ed2792
Revises: 487a10ab6c4e
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "02b470ed2792"
down_revision: str | None = "487a10ab6c4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS pricing")
    op.create_table('pricebooks',
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('pricebook_type', sa.String(length=32), nullable=False, comment='per_item | fixed_percentage'),
    sa.Column('sales_or_purchase_type', sa.String(length=16), nullable=False, comment='sales | purchases'),
    sa.Column('pricing_scheme', sa.String(length=16), nullable=True, comment='unit | volume (per_item books); NULL for fixed_percentage (Zoho sends "")'),
    sa.Column('percentage', sa.Numeric(precision=12, scale=6), nullable=True, comment='fixed_percentage: the markup (is_increase) or markdown percent'),
    sa.Column('pricebook_rate', sa.Numeric(precision=18, scale=6), nullable=True, comment="Book-level rate as Zoho sends it (observed = percentage); NOT a bracket's rate"),
    sa.Column('is_increase', sa.Boolean(), nullable=True, comment='true = markup, false = markdown'),
    sa.Column('rounding_type', sa.String(length=48), nullable=True, comment='Zoho rounding key (no_rounding, round_to_dollar …); applied to fixed_percentage quotes'),
    sa.Column('decimal_place', sa.SmallInteger(), nullable=True, comment='Digits for round_based_on_decimal'),
    sa.Column('is_default', sa.Boolean(), nullable=True, comment="Zoho's default pricebook flag (DETAIL document only; NULL until the detail lands)"),
    sa.Column('currency_id', sa.BigInteger(), nullable=True, comment='currency.currencies; NULL = the organization\'s base currency (Zoho sends "")'),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Engine-maintained echo of Zoho pricebook_id (not the identity of record)'),
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
    sa.CheckConstraint("btrim(name) <> ''", name='ck_pricebooks_name_not_blank'),
    sa.CheckConstraint("pricebook_type IN ('per_item','fixed_percentage')", name='ck_pricebooks_type'),
    sa.CheckConstraint("pricing_scheme IS NULL OR pricing_scheme IN ('unit','volume')", name='ck_pricebooks_scheme'),
    sa.CheckConstraint("sales_or_purchase_type IN ('sales','purchases')", name='ck_pricebooks_usage'),
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_pricebooks_status'),
    sa.CheckConstraint('decimal_place IS NULL OR decimal_place BETWEEN 0 AND 10', name='ck_pricebooks_decimal_place'),
    sa.ForeignKeyConstraint(['tenant_id', 'currency_id'], ['currency.currencies.tenant_id', 'currency.currencies.id'], name='fk_pricebooks_currency', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_pricebooks_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_pricebooks_scope_id'),
    schema='pricing',
    comment='Price lists (Zoho pricebooks) of one organization; Zoho crosswalk.'
    )
    op.create_index('ix_pricebooks_name_trgm', 'pricebooks', ['name'], unique=False, schema='pricing', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_pricebooks_org_usage_status', 'pricebooks', ['organization_id', 'sales_or_purchase_type', 'status'], unique=False, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_pricebooks_tenant_org', 'pricebooks', ['tenant_id', 'organization_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebooks_deleted_at'), 'pricebooks', ['deleted_at'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebooks_status'), 'pricebooks', ['status'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebooks_tenant_id'), 'pricebooks', ['tenant_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebooks_uuid'), 'pricebooks', ['uuid'], unique=True, schema='pricing')
    op.create_index('uq_pricebooks_zoho_id', 'pricebooks', ['tenant_id', 'zoho_id'], unique=True, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('pricebook_items',
    sa.Column('pricebook_id', sa.BigInteger(), nullable=False),
    sa.Column('item_zoho_id', sa.String(length=50), nullable=False, comment='Zoho item_id (no items module yet; an item_id FK joins it later)'),
    sa.Column('item_name', sa.Text(), nullable=True, comment='Item name as embedded in the pricebook (snapshot)'),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho pricebook_item_id — present for unit-scheme items only (verified live)'),
    sa.Column('pricebook_rate', sa.Numeric(precision=18, scale=6), nullable=True, comment='Unit-scheme price of the item'),
    sa.Column('pricebook_discount', sa.Text(), nullable=True, comment='Zoho\'s discount string verbatim (e.g. "5%"); NULL when Zoho sends ""'),
    sa.Column('can_be_sold', sa.Boolean(), nullable=True, comment='Item-master flag as embedded (snapshot)'),
    sa.Column('can_be_purchased', sa.Boolean(), nullable=True, comment='Item-master flag as embedded (snapshot)'),
    sa.Column('position', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
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
    sa.CheckConstraint("btrim(item_zoho_id) <> ''", name='ck_pricebook_items_item_ref'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'pricebook_id'], ['pricing.pricebooks.tenant_id', 'pricing.pricebooks.organization_id', 'pricing.pricebooks.id'], name='fk_pricebook_items_pricebook', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_pricebook_items_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_pricebook_items_scope_id'),
    schema='pricing',
    comment='Items of a per_item pricebook (unit rate, or parent of brackets).'
    )
    op.create_index('ix_pricebook_items_item', 'pricebook_items', ['item_zoho_id'], unique=False, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_pricebook_items_tenant_org', 'pricebook_items', ['tenant_id', 'organization_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_items_deleted_at'), 'pricebook_items', ['deleted_at'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_items_status'), 'pricebook_items', ['status'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_items_tenant_id'), 'pricebook_items', ['tenant_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_items_uuid'), 'pricebook_items', ['uuid'], unique=True, schema='pricing')
    op.create_index('uq_pricebook_items_book_item', 'pricebook_items', ['pricebook_id', 'item_zoho_id'], unique=True, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_pricebook_items_zoho_id', 'pricebook_items', ['tenant_id', 'zoho_id'], unique=True, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('pricebook_item_brackets',
    sa.Column('pricebook_item_id', sa.BigInteger(), nullable=False),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho price_brackets[].pricebook_item_id — identifies the BRACKET (verified live)'),
    sa.Column('start_quantity', sa.Numeric(precision=18, scale=6), nullable=True, comment='Inclusive lower bound'),
    sa.Column('end_quantity', sa.Numeric(precision=18, scale=6), nullable=True, comment='Upper bound; NULL = open-ended top bracket (Zoho sends "")'),
    sa.Column('pricebook_rate', sa.Numeric(precision=18, scale=6), nullable=True, comment='Unit price within this bracket'),
    sa.Column('pricebook_discount', sa.Text(), nullable=True, comment="Zoho's discount string verbatim"),
    sa.Column('position', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
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
    sa.CheckConstraint('end_quantity IS NULL OR start_quantity IS NULL OR end_quantity >= start_quantity', name='ck_pricebook_item_brackets_range'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'pricebook_item_id'], ['pricing.pricebook_items.tenant_id', 'pricing.pricebook_items.organization_id', 'pricing.pricebook_items.id'], name='fk_pricebook_item_brackets_item', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_pricebook_item_brackets_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='pricing',
    comment="Quantity brackets of a volume pricebook's item."
    )
    op.create_index('ix_pricebook_item_brackets_lookup', 'pricebook_item_brackets', ['pricebook_item_id', 'start_quantity'], unique=False, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_pricebook_item_brackets_tenant_org', 'pricebook_item_brackets', ['tenant_id', 'organization_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_item_brackets_deleted_at'), 'pricebook_item_brackets', ['deleted_at'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_item_brackets_status'), 'pricebook_item_brackets', ['status'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_item_brackets_tenant_id'), 'pricebook_item_brackets', ['tenant_id'], unique=False, schema='pricing')
    op.create_index(op.f('ix_pricing_pricebook_item_brackets_uuid'), 'pricebook_item_brackets', ['uuid'], unique=True, schema='pricing')
    op.create_index('uq_pricebook_item_brackets_zoho_id', 'pricebook_item_brackets', ['tenant_id', 'zoho_id'], unique=True, schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('uq_pricebook_item_brackets_zoho_id', table_name='pricebook_item_brackets', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.drop_index(op.f('ix_pricing_pricebook_item_brackets_uuid'), table_name='pricebook_item_brackets', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_item_brackets_tenant_id'), table_name='pricebook_item_brackets', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_item_brackets_status'), table_name='pricebook_item_brackets', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_item_brackets_deleted_at'), table_name='pricebook_item_brackets', schema='pricing')
    op.drop_index('ix_pricebook_item_brackets_tenant_org', table_name='pricebook_item_brackets', schema='pricing')
    op.drop_index('ix_pricebook_item_brackets_lookup', table_name='pricebook_item_brackets', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('pricebook_item_brackets', schema='pricing')
    op.drop_index('uq_pricebook_items_zoho_id', table_name='pricebook_items', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.drop_index('uq_pricebook_items_book_item', table_name='pricebook_items', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index(op.f('ix_pricing_pricebook_items_uuid'), table_name='pricebook_items', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_items_tenant_id'), table_name='pricebook_items', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_items_status'), table_name='pricebook_items', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebook_items_deleted_at'), table_name='pricebook_items', schema='pricing')
    op.drop_index('ix_pricebook_items_tenant_org', table_name='pricebook_items', schema='pricing')
    op.drop_index('ix_pricebook_items_item', table_name='pricebook_items', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('pricebook_items', schema='pricing')
    op.drop_index('uq_pricebooks_zoho_id', table_name='pricebooks', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.drop_index(op.f('ix_pricing_pricebooks_uuid'), table_name='pricebooks', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebooks_tenant_id'), table_name='pricebooks', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebooks_status'), table_name='pricebooks', schema='pricing')
    op.drop_index(op.f('ix_pricing_pricebooks_deleted_at'), table_name='pricebooks', schema='pricing')
    op.drop_index('ix_pricebooks_tenant_org', table_name='pricebooks', schema='pricing')
    op.drop_index('ix_pricebooks_org_usage_status', table_name='pricebooks', schema='pricing', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('ix_pricebooks_name_trgm', table_name='pricebooks', schema='pricing', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('pricebooks', schema='pricing')
    op.execute("DROP SCHEMA IF EXISTS pricing")
