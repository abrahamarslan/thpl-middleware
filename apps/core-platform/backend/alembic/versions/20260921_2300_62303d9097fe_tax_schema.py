"""Tax schema — components, groups, exemptions, grants, defaults, treatments

Replaces the single canonical ``tax.taxes`` with the six-table ``tax`` schema:

    tax_components               taxes AND tax groups (discriminated by tax_type)
    tax_group_members            which leaf components compose a group
    tax_exemptions               exemption reasons (P2 columns)
    organization_tax_components  organization ↔ component grants (M:N)
    org_default_tax_preferences  default component per organization + inter/intra
    gst_treatment_types          global GST / tax treatment vocabulary

Data is carried over, not re-synced: every ``tax.taxes`` row that satisfies the new
NOT NULL / CHECK contract keeps its id and public uuid, and its crosswalk rows
(``sync.sync_records`` and their history) are repointed at ``tax.tax_components``.
A row that cannot satisfy it (no name, no rate, an unknown tax_type, a rate outside
NUMERIC(7,4)) is NOT copied and its crosswalk row is deleted, so the next sync
recreates it from Zoho rather than this migration inventing a value. Operator
``notes`` (a dropped column) survive in ``app_metadata.legacy_notes``. The
``zoho_id`` echo is dropped — the crosswalk is the identity.

Downgrade rebuilds ``tax.taxes`` from the leaf components (groups, exemptions,
grants, defaults and treatments have no old home and are discarded).

Revision ID: 62303d9097fe
Revises: f84b5c2e60a7
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "62303d9097fe"
down_revision: str | None = "f84b5c2e60a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE_ZOHO = sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL")
_LIVE = sa.text("deleted_at IS NULL")

#: Rows of the old table that satisfy the new contract.
_VALID_OLD_ROW = """
    tax_name IS NOT NULL AND tax_name <> ''
    AND tax_percentage IS NOT NULL AND tax_percentage >= 0 AND tax_percentage < 1000
    AND tax_type IN ('tax', 'compound_tax')
"""


def upgrade() -> None:
    op.create_table('gst_treatment_types',
    sa.Column('owner_type', sa.Text(), nullable=True, comment="Polymorphic owner class: 'connection' / 'organization' / 'system'; NULL = unscoped"),
    sa.Column('owner_id', sa.BigInteger(), nullable=True, comment='Polymorphic owner id (resolve with owner_type); no FK'),
    sa.Column('code', sa.Integer(), nullable=False, comment="Source's small ordinal treatment code"),
    sa.Column('value', sa.Text(), nullable=False, comment="Natural key, e.g. 'business_gst'"),
    sa.Column('label', sa.Text(), nullable=True, comment='Source label'),
    sa.Column('value_formatted', sa.Text(), nullable=True, comment='Formatted display value from source'),
    sa.Column('description', sa.Text(), nullable=True, comment='Human-readable description of the treatment'),
    sa.Column('category', sa.Text(), nullable=True, comment="'business' or 'consumer'"),
    sa.Column('allowed_for_sales', sa.Boolean(), nullable=True, comment='NULL = unknown, treated conservatively by consumers'),
    sa.Column('allowed_for_purchase', sa.Boolean(), nullable=True, comment='NULL = unknown, treated conservatively'),
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
    sa.Column('content_hash', sa.String(length=64), nullable=True, comment='sha256 (hex) of the business payload — skip the write when unchanged'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("category IS NULL OR category IN ('business','consumer')", name='chk_gst_treatment_types_category'),
    sa.CheckConstraint("owner_type IS NULL OR owner_type IN ('connection','organization','system')", name='chk_gst_treatment_types_owner_type'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='GST / tax treatment vocabulary (global reference data).'
    )
    op.create_index('ix_gst_treatment_types_owner', 'gst_treatment_types', ['owner_type', 'owner_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_gst_treatment_types_deleted_at'), 'gst_treatment_types', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_gst_treatment_types_uuid'), 'gst_treatment_types', ['uuid'], unique=True, schema='tax')
    op.create_index('uq_gst_treatment_types_code', 'gst_treatment_types', ['code'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_gst_treatment_types_value', 'gst_treatment_types', ['value'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('tax_components',
    sa.Column('tax_name', sa.Text(), nullable=False, comment='Zoho tax or tax-group name'),
    sa.Column('tax_display_name', sa.Text(), nullable=True, comment='Display name override carried from Zoho'),
    sa.Column('tax_percentage', sa.Numeric(precision=7, scale=4), nullable=False, comment='Tax rate / group total percentage; Decimal, never float-parsed'),
    sa.Column('tax_type', sa.Text(), nullable=False, comment="Discriminator: 'tax' (a single component like CGST9), 'compound_tax' or 'tax_group' (a composite like GST18, see tax.tax_group_members)"),
    sa.Column('tax_specific_type', sa.Text(), nullable=True, comment="Edition-specific leg: IN cgst/sgst/igst/utgst/cess/nil, MX isr/iva/ieps, ZA soa_*/ciu_*; NULL for groups and for the generic 'tax' sentinel"),
    sa.Column('tax_factor', sa.Text(), nullable=True, comment='(Mexico) rate | share'),
    sa.Column('is_value_added', sa.Boolean(), nullable=True, comment='VAT-style tax'),
    sa.Column('tax_authority_id', sa.Text(), nullable=True, comment="Opaque external reference to the source's tax authority record (AP5)"),
    sa.Column('tax_authority_name', sa.Text(), nullable=True, comment='Display echo of the tax authority name'),
    sa.Column('country', sa.Text(), nullable=True, comment='(UK, EU, Global) country the tax belongs to'),
    sa.Column('country_code', sa.Text(), nullable=True, comment='(UK, EU, GCC, Global) two-letter country code'),
    sa.Column('output_tax_account_name', sa.Text(), nullable=True, comment='Chart-of-accounts display echo (not a local FK)'),
    sa.Column('purchase_tax_account_name', sa.Text(), nullable=True, comment='Chart-of-accounts display echo for the purchase side (not a local FK)'),
    sa.Column('tax_account_id', sa.Text(), nullable=True, comment="Opaque external reference to the source's chart-of-accounts entry (AP5)"),
    sa.Column('purchase_tax_account_id', sa.Text(), nullable=True, comment='Opaque external reference to the purchase-side chart-of-accounts entry (AP5)'),
    sa.Column('tds_payable_account_id', sa.Text(), nullable=True, comment='Opaque external reference to the TDS-payable chart-of-accounts entry (AP5)'),
    sa.Column('purchase_tax_expense_account_id', sa.BigInteger(), nullable=True, comment='(Australia, Canada) account purchase tax is computed in; documented as a long'),
    sa.Column('is_state_cess', sa.Boolean(), nullable=True, comment='State cess component flag; NULL = unknown'),
    sa.Column('is_inactive', sa.Boolean(), nullable=True, comment="The source's own deactivation flag; NULL = unknown/active. Distinct from deleted_at (no longer returned by the source) and deactivation_date (ours)"),
    sa.Column('is_default_tax', sa.Boolean(), nullable=True, comment='NULL = false'),
    sa.Column('is_editable', sa.Boolean(), nullable=True, comment='Operator may override at invoice time; NULL = unknown'),
    sa.Column('is_non_advol_tax', sa.Boolean(), nullable=True, comment='Non-ad-valorem flag; NULL = unknown/ad-valorem'),
    sa.Column('tax_specification', sa.Text(), nullable=True, comment="'inter' (inter-state) or 'intra' (intra-state)"),
    sa.Column('diff_rate_reason', sa.Text(), nullable=True, comment='Reason recorded when the rate differs from the standard'),
    sa.Column('start_date', sa.Date(), nullable=True, comment='Business date validity start (AP7); empty string from source -> NULL at ingest'),
    sa.Column('end_date', sa.Date(), nullable=True, comment='Business date validity end (AP7); same empty-string rule'),
    sa.Column('description', sa.Text(), nullable=True, comment='Free-text description'),
    sa.Column('reference_id', sa.Text(), nullable=True, comment='Opaque external reference (AP5)'),
    sa.Column('tax_name_formatted', sa.Text(), nullable=True, comment='Display cache from the default_taxes endpoint'),
    sa.Column('source_default_tax_type_code', sa.Integer(), nullable=True, comment='Raw legacy numeric tax_type (0/2) from default_taxes; audit only, never drives the tax_type CHECK (AP8)'),
    sa.Column('source_new_tax_type', sa.Text(), nullable=True, comment='Raw string tax_type from default_taxes; preferred mapping source'),
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
    sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivation_reason', sa.Text(), nullable=True),
    sa.Column('deactivated_by', sa.BigInteger(), nullable=True, comment='users.id who deactivated it'),
    sa.Column('content_hash', sa.String(length=64), nullable=True, comment='sha256 (hex) of the business payload — skip the write when unchanged'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("tax_specification IS NULL OR tax_specification IN ('inter','intra')", name='chk_tax_components_tax_specification'),
    sa.CheckConstraint("tax_type <> 'tax_group' OR tax_specific_type IS NULL", name='chk_tax_components_group_no_specific_type'),
    sa.CheckConstraint("tax_type IN ('tax','compound_tax','tax_group')", name='chk_tax_components_tax_type'),
    sa.CheckConstraint('tax_percentage >= 0', name='chk_tax_components_tax_percentage'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_tax_components_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_tax_components_tenant_id'),
    schema='tax',
    comment='Tax rates and tax groups (one id namespace, discriminated by tax_type).'
    )
    op.create_index('ix_tax_components_tenant_org', 'tax_components', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index('ix_tax_components_tenant_type', 'tax_components', ['tenant_id', 'tax_type'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_tax_tax_components_deleted_at'), 'tax_components', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_components_status'), 'tax_components', ['status'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_components_tenant_id'), 'tax_components', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_components_uuid'), 'tax_components', ['uuid'], unique=True, schema='tax')
    op.create_table('tax_exemptions',
    sa.Column('tax_exemption_code', sa.Text(), nullable=True, comment="P2 -- observed to contain individual persons' names used as ad-hoc per-customer labels rather than a category code; the erasure job must anonymize matching rows (manual/free-text matching, R15 decision 4)"),
    sa.Column('description', sa.Text(), nullable=True, comment='Free-text description'),
    sa.Column('type', sa.Text(), nullable=True, comment="Open text, no CHECK (AP8): only 'item' observed, vocabulary assumed source-defined and possibly larger than sampled"),
    sa.Column('type_formatted', sa.Text(), nullable=True, comment='Formatted echo of `type`'),
    sa.Column('exemption_name', sa.Text(), nullable=True, comment='P2 -- same contamination risk as tax_exemption_code; always empty in observed samples but not schema-guaranteed to stay that way'),
    sa.Column('exemption_type', sa.Text(), nullable=True, comment="Open text, no CHECK (AP8): only 'exempt' observed"),
    sa.Column('exemption_type_formatted', sa.Text(), nullable=True, comment='Formatted echo of `exemption_type`'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True, comment='sha256 (hex) of the business payload — skip the write when unchanged'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_tax_exemptions_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='Tax exemption reasons (P2: codes/names may hold personal names).'
    )
    op.create_index('ix_tax_exemptions_tenant_org', 'tax_exemptions', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_exemptions_deleted_at'), 'tax_exemptions', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_exemptions_tenant_id'), 'tax_exemptions', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_exemptions_uuid'), 'tax_exemptions', ['uuid'], unique=True, schema='tax')
    op.create_table('org_default_tax_preferences',
    sa.Column('tax_specification', sa.Text(), nullable=False, comment="'inter' (inter-state) or 'intra' (intra-state)"),
    sa.Column('default_tax_id', sa.BigInteger(), nullable=False, comment='The tax component that is the default for this context'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("tax_specification IN ('inter','intra')", name='chk_org_default_tax_preferences_spec'),
    sa.ForeignKeyConstraint(['tenant_id', 'default_tax_id'], ['tax.tax_components.tenant_id', 'tax.tax_components.id'], name='fk_org_default_tax_preferences_default_tax', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_org_default_tax_preferences_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='Default tax component per organization and inter/intra context.'
    )
    op.create_index('ix_org_default_tax_preferences_default_tax_id', 'org_default_tax_preferences', ['default_tax_id'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_org_default_tax_preferences_tenant_org', 'org_default_tax_preferences', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_org_default_tax_preferences_deleted_at'), 'org_default_tax_preferences', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_org_default_tax_preferences_tenant_id'), 'org_default_tax_preferences', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_org_default_tax_preferences_uuid'), 'org_default_tax_preferences', ['uuid'], unique=True, schema='tax')
    op.create_index('uq_org_default_tax_preferences_org_spec', 'org_default_tax_preferences', ['tenant_id', 'organization_id', 'tax_specification'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'), postgresql_nulls_not_distinct=True)
    op.create_table('organization_tax_components',
    sa.Column('tax_component_id', sa.BigInteger(), nullable=False, comment='The tax rate/group assigned to the organization'),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment="Per-organization enablement switch (distinct from the component's own flags)"),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_organization_tax_components_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_component_id'], ['tax.tax_components.tenant_id', 'tax.tax_components.id'], name='fk_organization_tax_components_component', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='Which organizations may use which tax components (M:N).'
    )
    op.create_index('ix_organization_tax_components_tax_component_id', 'organization_tax_components', ['tax_component_id'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_organization_tax_components_tenant_org', 'organization_tax_components', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_organization_tax_components_deleted_at'), 'organization_tax_components', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_organization_tax_components_tenant_id'), 'organization_tax_components', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_organization_tax_components_uuid'), 'organization_tax_components', ['uuid'], unique=True, schema='tax')
    op.create_index('uq_organization_tax_components_org_tax', 'organization_tax_components', ['tenant_id', 'organization_id', 'tax_component_id'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('tax_group_members',
    sa.Column('tax_group_id', sa.BigInteger(), nullable=False, comment="The composite group row (tax_components.tax_type = 'tax_group')"),
    sa.Column('member_tax_id', sa.BigInteger(), nullable=False, comment="The component that is a member (tax_components.tax_type = 'tax')"),
    sa.Column('position', sa.SmallInteger(), nullable=True, comment="Display order (index in the source's taxes[] array)"),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint('tax_group_id <> member_tax_id', name='chk_tax_group_members_not_self'),
    sa.ForeignKeyConstraint(['tenant_id', 'member_tax_id'], ['tax.tax_components.tenant_id', 'tax.tax_components.id'], name='fk_tax_group_members_member', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_tax_group_members_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'tax_group_id'], ['tax.tax_components.tenant_id', 'tax.tax_components.id'], name='fk_tax_group_members_group', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='Leaf components composing a tax group.'
    )
    op.create_index('ix_tax_group_members_member_tax_id', 'tax_group_members', ['member_tax_id'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_tax_group_members_tenant_org', 'tax_group_members', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_group_members_deleted_at'), 'tax_group_members', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_group_members_tenant_id'), 'tax_group_members', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_group_members_uuid'), 'tax_group_members', ['uuid'], unique=True, schema='tax')
    op.create_index('uq_tax_group_members_group_member', 'tax_group_members', ['tax_group_id', 'member_tax_id'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))

    # ── carry the data over ─────────────────────────────────────────────────
    op.execute(f"""
        INSERT INTO tax.tax_components (
            id, uuid, tenant_id, organization_id,
            tax_name, tax_percentage, tax_type, tax_specific_type, tax_factor,
            tax_authority_id, tax_authority_name, is_value_added, is_default_tax, is_editable,
            country, country_code, tax_account_id, purchase_tax_account_id,
            output_tax_account_name, purchase_tax_account_name, tds_payable_account_id,
            purchase_tax_expense_account_id,
            created_by, created_by_name, updated_by, updated_by_name,
            status, is_verified, row_version, app_version, app_metadata,
            created_at, updated_at,
            deactivation_date, deactivation_reason, deactivated_by,
            deleted_at, deleted_by, deleted_reason
        )
        SELECT
            id, uuid, tenant_id, organization_id,
            tax_name, tax_percentage, tax_type,
            NULLIF(NULLIF(lower(btrim(tax_specific_type)), ''), 'tax'), tax_factor,
            tax_authority_id, tax_authority_name, is_value_added, is_default_tax, is_editable,
            country, country_code, tax_account_id, purchase_tax_account_id,
            output_tax_account_name, purchase_tax_account_name, tds_payable_account_id,
            purchase_tax_expense_account_id,
            created_by, created_by_name, updated_by, updated_by_name,
            status, is_verified, row_version, app_version,
            CASE WHEN notes IS NULL THEN app_metadata
                 ELSE app_metadata || jsonb_build_object('legacy_notes', notes) END,
            created_at, updated_at,
            deactivation_date, deactivation_reason, deactivated_by,
            deleted_at, deleted_by, deleted_reason
        FROM tax.taxes
        WHERE {_VALID_OLD_ROW}
    """)
    op.execute("""
        SELECT setval(pg_get_serial_sequence('tax.tax_components', 'id'),
                      GREATEST((SELECT COALESCE(MAX(id), 0) FROM tax.tax_components), 1),
                      (SELECT COUNT(*) > 0 FROM tax.tax_components))
    """)
    # A crosswalk row whose entity was not carried over is deleted (the next
    # sync recreates the pair); the survivors are repointed, history included.
    for table in ("sync.sync_records", "sync.sync_payloads"):
        op.execute(f"""
            DELETE FROM {table}
            WHERE entity_table = 'tax.taxes'
              AND (entity_id IS NULL OR entity_id NOT IN (SELECT id FROM tax.tax_components))
        """)
        op.execute(f"UPDATE {table} SET entity_table = 'tax.tax_components' WHERE entity_table = 'tax.taxes'")

    op.drop_table('taxes', schema='tax')


def downgrade() -> None:
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
        schema='tax',
        comment="Canonical tax master (rates, authorities, accounts).",
    )

    op.create_index("uq_taxes_zoho_id_live", "taxes", ["tenant_id", "zoho_id"], unique=True,
                    schema='tax', postgresql_where=_LIVE_ZOHO)
    op.create_index("ix_taxes_tenant_name", "taxes", ["tenant_id", "tax_name"], unique=False,
                    schema='tax', postgresql_where=_LIVE)
    op.create_index("ix_taxes_specific_type", "taxes", ["tenant_id", "tax_specific_type"],
                    unique=False, schema='tax', postgresql_where=_LIVE)
    op.create_index("ix_taxes_tenant_org", "taxes", ["tenant_id", "organization_id"],
                    unique=False, schema='tax')
    op.create_index("ix_tax_taxes_deleted_at", "taxes", ["deleted_at"], unique=False, schema='tax')
    op.create_index("ix_tax_taxes_status", "taxes", ["status"], unique=False, schema='tax')
    op.create_index("ix_tax_taxes_tenant_id", "taxes", ["tenant_id"], unique=False, schema='tax')
    op.create_index("ix_tax_taxes_uuid", "taxes", ["uuid"], unique=True, schema='tax')
    op.create_index("ix_tax_taxes_zoho_id", "taxes", ["zoho_id"], unique=False, schema='tax')

    op.execute("""
        INSERT INTO tax.taxes (
            id, uuid, tenant_id, organization_id,
            tax_name, tax_percentage, tax_type, tax_specific_type, tax_factor,
            tax_authority_id, tax_authority_name, is_value_added, is_default_tax, is_editable,
            country, country_code, tax_account_id, purchase_tax_account_id,
            output_tax_account_name, purchase_tax_account_name, tds_payable_account_id,
            purchase_tax_expense_account_id,
            created_by, created_by_name, updated_by, updated_by_name,
            status, is_verified, row_version, app_version, app_metadata,
            created_at, updated_at,
            deactivation_date, deactivation_reason, deactivated_by,
            deleted_at, deleted_by, deleted_reason
        )
        SELECT
            id, uuid, tenant_id, organization_id,
            tax_name, tax_percentage, tax_type, tax_specific_type, tax_factor,
            tax_authority_id, tax_authority_name, is_value_added, is_default_tax, is_editable,
            country, country_code, tax_account_id, purchase_tax_account_id,
            output_tax_account_name, purchase_tax_account_name, tds_payable_account_id,
            purchase_tax_expense_account_id,
            created_by, created_by_name, updated_by, updated_by_name,
            status, is_verified, row_version, app_version, app_metadata - 'legacy_notes',
            created_at, updated_at,
            deactivation_date, deactivation_reason, deactivated_by,
            deleted_at, deleted_by, deleted_reason
        FROM tax.tax_components
        WHERE tax_type IN ('tax', 'compound_tax')
    """)
    op.execute("UPDATE tax.taxes SET notes = app_metadata_notes.n FROM ("
               "SELECT id, app_metadata ->> 'legacy_notes' AS n FROM tax.tax_components) AS app_metadata_notes "
               "WHERE tax.taxes.id = app_metadata_notes.id AND app_metadata_notes.n IS NOT NULL")
    op.execute("""
        SELECT setval(pg_get_serial_sequence('tax.taxes', 'id'),
                      GREATEST((SELECT COALESCE(MAX(id), 0) FROM tax.taxes), 1),
                      (SELECT COUNT(*) > 0 FROM tax.taxes))
    """)
    # The zoho_id echo is re-derived from the crosswalk.
    op.execute("""
        UPDATE tax.taxes t SET zoho_id = x.external_id
        FROM sync.sync_records x
        WHERE x.module = 'taxes' AND x.entity_table = 'tax.tax_components' AND x.entity_id = t.id
    """)
    # Group rows have no old home: their crosswalk rows go with them.
    for table in ("sync.sync_records", "sync.sync_payloads"):
        op.execute(f"""
            DELETE FROM {table}
            WHERE entity_table = 'tax.tax_components'
              AND (entity_id IS NULL OR entity_id NOT IN (SELECT id FROM tax.taxes))
        """)
        op.execute(f"UPDATE {table} SET entity_table = 'tax.taxes' WHERE entity_table = 'tax.tax_components'")

    for table in ("tax_group_members", "organization_tax_components", "org_default_tax_preferences",
                  "tax_exemptions", "tax_components", "gst_treatment_types"):
        op.drop_table(table, schema="tax")
