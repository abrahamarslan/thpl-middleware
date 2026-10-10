"""Parties: customers and vendors (Zoho contacts), contact persons, learned payment terms, tax registrations.

    party.payment_terms     payment terms as Zoho names them (learned from contacts; Zoho id = identity)
    party.parties           one customer or vendor of one organization (Zoho crosswalk module ``parties``)
    party.contact_persons   people of a party (Zoho crosswalk module ``contact_persons``); one primary
    tax.tax_registrations   GSTIN / PAN / Udyam / VAT of any owner (polymorphic, ``core.entity_types``)

Changes to existing schemas:

    geo.place_links.zoho_id               Zoho address_id of an owner's address (the LINK, never the place)
    geo.place_links owner_type CHECK      + 'party'
    extfields.field_definitions           + zoho_field_id (Zoho field_id), + options (learned dropdown options)

Registrations (rows, not DDL): ``core.entity_types`` ``party`` / ``contact_person``; ``party`` may carry
taxes (one default tax + an exemption), account assignments (receivable / payable / sales / purchase,
falling back to the organization for the control accounts) and comments; ``contact_person`` comments.
Custom fields, documents, media, addresses and categories need only the entity type. Permissions:
``party.party:update|manage``, ``party.contact_person:update``.

The party → primary person FK closes a cycle with ``contact_persons.party_id``; it is created after
both tables, DEFERRABLE INITIALLY DEFERRED (the sync inserts persons and points at one in one flush).

Downgrade removes all of it (registrations included).

Revision ID: 934e2e5ea8cb
Revises: 7c3e91a05d24
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "934e2e5ea8cb"
down_revision: str | None = "7c3e91a05d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_TYPES_BEFORE = ("user", "organization", "department", "team", "customer", "contact_person", "vendor",
                       "warehouse", "zoho_location", "invoice", "estimate", "sales_order", "purchase_order",
                       "shipment")
_OWNER_TYPES_AFTER = ("user", "organization", "department", "team", "customer", "party", "contact_person",
                      "vendor", "warehouse", "zoho_location", "invoice", "estimate", "sales_order",
                      "purchase_order", "shipment")


def _owner_type_check(types: tuple[str, ...]) -> None:
    op.drop_constraint("chk_place_link_owner_type", "place_links", schema="geo", type_="check")
    op.create_check_constraint("chk_place_link_owner_type", "place_links",
                               "owner_type IN (" + ",".join(f"'{t}'" for t in types) + ")", schema="geo")


_REGISTRATION_INTEGRITY = """
    CREATE FUNCTION tax.check_tax_registration_integrity() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        -- Same rule as tax_assignments: the owner exists, in this tenant AND organization
        -- (an organization owns itself). Deferred, so a party and its registrations land in one flush.
        IF NEW.deleted_at IS NULL THEN
            PERFORM core.assert_owner_scope(NEW.owner_type_code, NEW.owner_id, NEW.tenant_id, NEW.organization_id);
        END IF;
        RETURN NULL;
    END $$
"""
# Separate statement: asyncpg runs one command per execute.
_REGISTRATION_TRIGGER = """
    CREATE CONSTRAINT TRIGGER ctrg_tax_registrations_integrity
        AFTER INSERT OR UPDATE OF owner_type_code, owner_id, tenant_id, organization_id, deleted_at
        ON tax.tax_registrations DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION tax.check_tax_registration_integrity()
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS party")
    op.execute("COMMENT ON SCHEMA party IS 'Commercial parties: customers and vendors, their persons and terms.'")
    op.create_table('payment_terms',
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho payment_terms_id; NULL = a local term'),
    sa.Column('payment_terms', sa.Integer(), nullable=False, comment="Zoho code: >= 0 = net days; < 0 = a rule (-3 = 'Due end of next month', observed live)"),
    sa.Column('label', sa.Text(), nullable=False, comment='Zoho payment_terms_label, verbatim'),
    sa.Column('net_days', sa.Integer(), sa.Computed('CASE WHEN payment_terms >= 0 THEN payment_terms END', persisted=True), nullable=True, comment='Net days when the code is a day count (generated)'),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='When a party payload first named it'),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
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
    sa.CheckConstraint("btrim(label) <> ''", name='ck_payment_terms_label_not_blank'),
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_payment_terms_status'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_payment_terms_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_payment_terms_scope_id'),
    schema='party',
    comment='Payment terms as Zoho names them (Zoho id = identity; code < 0 = a rule, not days).'
    )
    op.create_index(op.f('ix_party_payment_terms_deleted_at'), 'payment_terms', ['deleted_at'], unique=False, schema='party')
    op.create_index(op.f('ix_party_payment_terms_status'), 'payment_terms', ['status'], unique=False, schema='party')
    op.create_index(op.f('ix_party_payment_terms_tenant_id'), 'payment_terms', ['tenant_id'], unique=False, schema='party')
    op.create_index(op.f('ix_party_payment_terms_uuid'), 'payment_terms', ['uuid'], unique=True, schema='party')
    op.create_index('ix_payment_terms_tenant_org', 'payment_terms', ['tenant_id', 'organization_id'], unique=False, schema='party')
    op.create_index('uq_payment_terms_zoho_id', 'payment_terms', ['tenant_id', 'zoho_id'], unique=True, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('tax_registrations',
    sa.Column('owner_type_code', sa.String(length=64), nullable=False, comment='core.entity_types.code of the owner (party, organization …)'),
    sa.Column('owner_id', sa.BigInteger(), nullable=False),
    sa.Column('registration_type', sa.String(length=20), nullable=False),
    sa.Column('registration_number', sa.Text(), nullable=False, comment='Normalized: upper-case, no spaces'),
    sa.Column('legal_name', sa.Text(), nullable=True),
    sa.Column('trade_name', sa.Text(), nullable=True),
    sa.Column('place_of_supply', sa.String(length=4), nullable=True, comment='GST state code of this registration'),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment='Type-specific facts, e.g. udyam: {msme_type, is_valid, validated_at}'),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho tax_info_id (GSTIN rows)'),
    sa.Column('source_system', sa.String(length=16), nullable=True, comment="'zoho' | NULL (local)"),
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
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("btrim(registration_number) <> ''", name='ck_tax_registrations_number_not_blank'),
    sa.CheckConstraint("registration_type IN ('gstin','pan','udyam','vat','tax_reg_no')", name='ck_tax_registrations_type'),
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_tax_registrations_status'),
    sa.CheckConstraint('owner_id > 0', name='ck_tax_registrations_owner_id'),
    sa.CheckConstraint('valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from', name='ck_tax_registrations_validity'),
    sa.ForeignKeyConstraint(['owner_type_code'], ['core.entity_types.code'], name='fk_tax_registrations_owner_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_tax_registrations_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='tax',
    comment='Statutory registrations (GSTIN, PAN, Udyam, VAT …) of any owner.'
    )
    op.create_index('ix_tax_registrations_lookup', 'tax_registrations', ['tenant_id', 'registration_type', 'registration_number'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_tax_registrations_owner', 'tax_registrations', ['tenant_id', 'owner_type_code', 'owner_id'], unique=False, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_tax_registrations_tenant_org', 'tax_registrations', ['tenant_id', 'organization_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_registrations_deleted_at'), 'tax_registrations', ['deleted_at'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_registrations_status'), 'tax_registrations', ['status'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_registrations_tenant_id'), 'tax_registrations', ['tenant_id'], unique=False, schema='tax')
    op.create_index(op.f('ix_tax_tax_registrations_uuid'), 'tax_registrations', ['uuid'], unique=True, schema='tax')
    op.create_index(op.f('ix_tax_tax_registrations_verification_status'), 'tax_registrations', ['verification_status'], unique=False, schema='tax')
    op.create_index('uq_tax_registrations_number', 'tax_registrations', ['tenant_id', 'owner_type_code', 'owner_id', 'registration_type', 'registration_number'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_tax_registrations_one_primary', 'tax_registrations', ['tenant_id', 'owner_type_code', 'owner_id', 'registration_type'], unique=True, schema='tax', postgresql_where=sa.text('is_primary AND deleted_at IS NULL'))
    op.create_index('uq_tax_registrations_zoho_id', 'tax_registrations', ['tenant_id', 'zoho_id'], unique=True, schema='tax', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('parties',
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Engine-maintained echo of Zoho contact_id (not the identity of record)'),
    sa.Column('contact_number', sa.Text(), nullable=True, comment='Zoho contact_number (optional)'),
    sa.Column('source_created_at', sa.DateTime(timezone=True), nullable=True, comment='Zoho created_time (party since)'),
    sa.Column('name', sa.Text(), nullable=False, comment='Display name (Zoho contact_name)'),
    sa.Column('company_name', sa.Text(), nullable=True),
    sa.Column('legal_name', sa.Text(), nullable=True, comment='Legal name (GST registration)'),
    sa.Column('trade_name', sa.Text(), nullable=True, comment='Trade name (Zoho trader_name)'),
    sa.Column('salutation', sa.String(length=25), nullable=True, comment='Zoho contact_salutation'),
    sa.Column('first_name', sa.String(length=100), nullable=True, comment="Zoho's party-level echo of the primary person"),
    sa.Column('last_name', sa.String(length=100), nullable=True),
    sa.Column('designation', sa.String(length=100), nullable=True),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('party_type', sa.String(length=16), nullable=False, comment='customer | vendor (Zoho contact_type)'),
    sa.Column('customer_sub_type', sa.String(length=16), nullable=True, comment='business | individual'),
    sa.Column('source', sa.String(length=32), nullable=True, comment='Zoho source: api | csv | user …'),
    sa.Column('language_code', sa.String(length=10), nullable=True),
    sa.Column('is_base_currency_only', sa.Boolean(), nullable=True, comment='Zoho is_bcy_only_contact'),
    sa.Column('price_list_id', sa.BigInteger(), nullable=True, comment='Zoho pricebook_id → pricing.price_lists'),
    sa.Column('payment_term_id', sa.BigInteger(), nullable=True, comment="Zoho payment_terms_id → party.payment_terms; NULL when Zoho sends ''"),
    sa.Column('payment_terms', sa.Integer(), nullable=True, comment='Zoho payment-terms code (always carried)'),
    sa.Column('payment_terms_label', sa.Text(), nullable=True),
    sa.Column('credit_limit', sa.Numeric(precision=18, scale=2), nullable=True, comment='Customers'),
    sa.Column('is_taxable', sa.Boolean(), nullable=True, comment='Absent on vendors → NULL, not false'),
    sa.Column('place_of_supply', sa.String(length=4), nullable=True, comment='GST state code (Zoho place_of_contact)'),
    sa.Column('gst_treatment', sa.String(length=40), nullable=True, comment='tax.gst_treatment_types.value (no CHECK: Zoho sends undocumented values)'),
    sa.Column('contact_category', sa.String(length=40), nullable=True, comment='Zoho contact_category'),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('mobile', sa.String(length=50), nullable=True),
    sa.Column('website', sa.Text(), nullable=True),
    sa.Column('facebook', sa.String(length=100), nullable=True),
    sa.Column('twitter', sa.String(length=100), nullable=True),
    sa.Column('is_sms_enabled', sa.Boolean(), nullable=True),
    sa.Column('payment_reminder_enabled', sa.Boolean(), nullable=True),
    sa.Column('portal_status', sa.String(length=16), nullable=True, comment='Zoho portal_status'),
    sa.Column('primary_contact_person_id', sa.BigInteger(), nullable=True, comment='Zoho primary_contact_id → party.contact_persons'),
    sa.Column('owner_zoho_user_id', sa.BigInteger(), nullable=True, comment='Zoho owner_id → zoho_users'),
    sa.Column('merged_into_party_id', sa.BigInteger(), nullable=True, comment='The survivor after a Zoho merge of duplicates (cf_merged_customer_ids)'),
    sa.Column('consent_agreed', sa.Boolean(), nullable=True, comment='Zoho is_consent_agreed (DPDP)'),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True, comment='Zoho consent_date'),
    sa.Column('has_transaction', sa.Boolean(), nullable=True),
    sa.Column('is_associated_to_branch', sa.Boolean(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True, comment='Zoho notes (internal discussion = comments)'),
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
    sa.Column('currency_id', sa.BigInteger(), nullable=True, comment="currency.currencies; NULL = the organization's base currency"),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("btrim(name) <> ''", name='ck_parties_name_not_blank'),
    sa.CheckConstraint("customer_sub_type IS NULL OR customer_sub_type IN ('business','individual')", name='ck_parties_customer_sub_type'),
    sa.CheckConstraint("party_type IN ('customer','vendor')", name='ck_parties_type'),
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_parties_status'),
    sa.CheckConstraint("verification_status IN ('unverified','geocoded_only','field_verified','disputed')", name='ck_parties_verification_status'),
    sa.CheckConstraint('credit_limit IS NULL OR credit_limit >= 0', name='ck_parties_credit_limit'),
    sa.CheckConstraint('merged_into_party_id IS NULL OR merged_into_party_id <> id', name='ck_parties_not_merged_into_self'),
    sa.ForeignKeyConstraint(['owner_zoho_user_id'], ['zoho_users.id'], name='fk_parties_owner_zoho_user', ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id', 'currency_id'], ['currency.currencies.tenant_id', 'currency.currencies.id'], name='fk_parties_currency', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'merged_into_party_id'], ['party.parties.tenant_id', 'party.parties.organization_id', 'party.parties.id'], name='fk_parties_merged_into', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'payment_term_id'], ['party.payment_terms.tenant_id', 'party.payment_terms.organization_id', 'party.payment_terms.id'], name='fk_parties_payment_term', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'price_list_id'], ['pricing.price_lists.tenant_id', 'pricing.price_lists.organization_id', 'pricing.price_lists.id'], name='fk_parties_price_list', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_parties_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_parties_scope_id'),
    schema='party',
    comment='Customers and vendors of one organization (Zoho contacts); Zoho crosswalk module parties.'
    )
    op.create_index('ix_parties_company_trgm', 'parties', ['company_name'], unique=False, schema='party', postgresql_using='gin', postgresql_ops={'company_name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL AND company_name IS NOT NULL'))
    op.create_index('ix_parties_email_lower', 'parties', ['organization_id', sa.literal_column('lower(email)')], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND email IS NOT NULL'))
    op.create_index('ix_parties_merged_into', 'parties', ['merged_into_party_id'], unique=False, schema='party', postgresql_where=sa.text('merged_into_party_id IS NOT NULL'))
    op.create_index('ix_parties_mobile_last10', 'parties', ['organization_id', sa.literal_column("right(regexp_replace(mobile, '\\D', '', 'g'), 10)")], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND mobile IS NOT NULL'))
    op.create_index('ix_parties_name_trgm', 'parties', ['name'], unique=False, schema='party', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_parties_org_type_status', 'parties', ['organization_id', 'party_type', 'status'], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_parties_price_list', 'parties', ['price_list_id'], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND price_list_id IS NOT NULL'))
    op.create_index('ix_parties_tenant_org', 'parties', ['tenant_id', 'organization_id'], unique=False, schema='party')
    op.create_index(op.f('ix_party_parties_deleted_at'), 'parties', ['deleted_at'], unique=False, schema='party')
    op.create_index(op.f('ix_party_parties_status'), 'parties', ['status'], unique=False, schema='party')
    op.create_index(op.f('ix_party_parties_tenant_id'), 'parties', ['tenant_id'], unique=False, schema='party')
    op.create_index(op.f('ix_party_parties_uuid'), 'parties', ['uuid'], unique=True, schema='party')
    op.create_index(op.f('ix_party_parties_verification_status'), 'parties', ['verification_status'], unique=False, schema='party')
    op.create_index('uq_parties_zoho_id', 'parties', ['tenant_id', 'zoho_id'], unique=True, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('contact_persons',
    sa.Column('party_id', sa.BigInteger(), nullable=False),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho contact_person_id'),
    sa.Column('user_id', sa.BigInteger(), nullable=True, comment='LOCAL: the platform user this person signs in as (portal / app), when they have one'),
    sa.Column('salutation', sa.String(length=25), nullable=True),
    sa.Column('first_name', sa.String(length=100), nullable=True),
    sa.Column('last_name', sa.String(length=100), nullable=True),
    sa.Column('display_name', sa.Text(), sa.Computed("NULLIF(btrim(coalesce(btrim(first_name), '') || ' ' || coalesce(btrim(last_name), '')), '')", persisted=True), nullable=True, comment='first + last (generated)'),
    sa.Column('designation', sa.String(length=100), nullable=True),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('mobile', sa.String(length=50), nullable=True),
    sa.Column('mobile_country_code', sa.String(length=8), nullable=True),
    sa.Column('fax', sa.String(length=50), nullable=True),
    sa.Column('skype', sa.String(length=100), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Zoho is_primary_contact'),
    sa.Column('is_email_enabled', sa.Boolean(), nullable=True, comment='communication_preference.is_email_enabled'),
    sa.Column('is_whatsapp_enabled', sa.Boolean(), nullable=True, comment='communication_preference.is_whatsapp_enabled'),
    sa.Column('is_sms_enabled', sa.Boolean(), nullable=True, comment='Zoho is_sms_enabled_for_cp'),
    sa.Column('is_whatsapp_disabled_by_customer', sa.Boolean(), nullable=True),
    sa.Column('can_invite', sa.Boolean(), nullable=True),
    sa.Column('is_added_in_portal', sa.Boolean(), nullable=True),
    sa.Column('is_portal_invitation_accepted', sa.Boolean(), nullable=True),
    sa.Column('is_portal_mfa_enabled', sa.Boolean(), nullable=True),
    sa.Column('portal_enabled_via', sa.String(length=16), nullable=True),
    sa.Column('position', sa.SmallInteger(), server_default=sa.text('0'), nullable=False, comment="Order in Zoho's array"),
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
    sa.CheckConstraint("status IN ('active','inactive')", name='ck_contact_persons_status'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'party_id'], ['party.parties.tenant_id', 'party.parties.organization_id', 'party.parties.id'], name='fk_contact_persons_party', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_contact_persons_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_contact_persons_user', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_contact_persons_scope_id'),
    schema='party',
    comment='People of a party (Zoho contact_persons[]); Zoho crosswalk module contact_persons.'
    )
    op.create_index('ix_contact_persons_email_lower', 'contact_persons', ['organization_id', sa.literal_column('lower(email)')], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND email IS NOT NULL'))
    op.create_index('ix_contact_persons_mobile_last10', 'contact_persons', ['organization_id', sa.literal_column("right(regexp_replace(mobile, '\\D', '', 'g'), 10)")], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND mobile IS NOT NULL'))
    op.create_index('ix_contact_persons_party', 'contact_persons', ['party_id', 'position'], unique=False, schema='party', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_contact_persons_tenant_org', 'contact_persons', ['tenant_id', 'organization_id'], unique=False, schema='party')
    op.create_index('ix_contact_persons_user', 'contact_persons', ['user_id'], unique=False, schema='party', postgresql_where=sa.text('user_id IS NOT NULL'))
    op.create_index(op.f('ix_party_contact_persons_deleted_at'), 'contact_persons', ['deleted_at'], unique=False, schema='party')
    op.create_index(op.f('ix_party_contact_persons_status'), 'contact_persons', ['status'], unique=False, schema='party')
    op.create_index(op.f('ix_party_contact_persons_tenant_id'), 'contact_persons', ['tenant_id'], unique=False, schema='party')
    op.create_index(op.f('ix_party_contact_persons_uuid'), 'contact_persons', ['uuid'], unique=True, schema='party')
    op.create_index('uq_contact_persons_one_primary', 'contact_persons', ['party_id'], unique=True, schema='party', postgresql_where=sa.text('is_primary AND deleted_at IS NULL'))
    op.create_index('uq_contact_persons_zoho_id', 'contact_persons', ['tenant_id', 'zoho_id'], unique=True, schema='party', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.add_column('field_definitions', sa.Column('zoho_field_id', sa.String(length=50), nullable=True, comment='Zoho field_id / customfield_id (immutable); NULL = a local definition'), schema='extfields')
    op.add_column('field_definitions', sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Dropdown options learned from values: [{id, value, color_code}] (Zoho sends the selected option only, so the list grows as values are seen)'), schema='extfields')
    op.create_index('uq_field_definitions_zoho_field', 'field_definitions', ['tenant_id', 'organization_id', 'owner_type_code', 'zoho_field_id'], unique=True, schema='extfields', postgresql_where=sa.text('deleted_at IS NULL AND zoho_field_id IS NOT NULL'))
    op.add_column('place_links', sa.Column('zoho_id', sa.String(length=50), nullable=True, comment="Zoho address_id of this owner's address; NULL = local. Zoho-owned when set"), schema='geo')
    op.create_index('uq_place_links_zoho_id', 'place_links', ['tenant_id', 'zoho_id'], unique=True, schema='geo', postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_foreign_key(
        "fk_parties_primary_person", "parties", "contact_persons",
        ["tenant_id", "organization_id", "primary_contact_person_id"], ["tenant_id", "organization_id", "id"],
        source_schema="party", referent_schema="party", ondelete="RESTRICT", deferrable=True, initially="DEFERRED",
    )
    _owner_type_check(_OWNER_TYPES_AFTER)
    op.execute(_REGISTRATION_INTEGRITY)
    op.execute(_REGISTRATION_TRIGGER)

    bind = op.get_bind()
    from app.modules.accounting.registration import register_account_owner_type
    from app.modules.comments.registration import register_commentable_entity_type
    from app.modules.taxes.registration import register_taxable_entity_type

    bind.execute(sa.text(
        "INSERT INTO core.entity_types (code, name, target_schema, target_table, description, created_by_name) VALUES "
        "('party', 'Party', 'party', 'parties', 'A customer or vendor (Zoho contact).', 'system:migration'), "
        "('contact_person', 'Contact person', 'party', 'contact_persons', 'A person of a party.', 'system:migration') "
        "ON CONFLICT (code) DO NOTHING"))
    register_taxable_entity_type(
        bind, code="party", name="Party", target_schema="party", target_table="parties",
        allows_multiple=False, allows_exemption=True,
        description="A party's default tax (Zoho tax_id) and exemption (tax_exemption_id).",
    )
    register_account_owner_type(
        bind, code="party", name="Party", target_schema="party", target_table="parties",
        purposes={"receivable": True, "payable": True, "sales": False, "purchase": False},
        description="A party's own control / income / expense accounts (Zoho account_id).",
    )
    register_commentable_entity_type(bind, code="party", name="Party", target_schema="party",
                                     target_table="parties", description="Notes on a customer or vendor.")
    register_commentable_entity_type(bind, code="contact_person", name="Contact person", target_schema="party",
                                     target_table="contact_persons", description="Notes on a contact person.")

    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DELETE FROM comments.commentable_entity_types WHERE entity_type_code IN ('party', 'contact_person')",
        "DELETE FROM accounting.account_purpose_policies WHERE entity_type_code = 'party'",
        "DELETE FROM tax.taxable_entity_types WHERE entity_type_code = 'party'",
    ):
        bind.execute(sa.text(statement))
    op.execute("DROP TRIGGER IF EXISTS ctrg_tax_registrations_integrity ON tax.tax_registrations")
    op.execute("DROP FUNCTION IF EXISTS tax.check_tax_registration_integrity()")
    op.drop_constraint("fk_parties_primary_person", "parties", schema="party", type_="foreignkey")
    op.drop_index("uq_field_definitions_zoho_field", table_name="field_definitions", schema="extfields")
    op.drop_column("field_definitions", "options", schema="extfields")
    op.drop_column("field_definitions", "zoho_field_id", schema="extfields")
    op.execute("DELETE FROM geo.place_links WHERE owner_type = 'party'")
    _owner_type_check(_OWNER_TYPES_BEFORE)
    op.drop_index("uq_place_links_zoho_id", table_name="place_links", schema="geo")
    op.drop_column("place_links", "zoho_id", schema="geo")
    op.drop_table("contact_persons", schema="party")
    op.drop_table("parties", schema="party")
    op.drop_table("tax_registrations", schema="tax")
    op.drop_table("payment_terms", schema="party")
    # Entity types last: tax_registrations / field values reference them.
    bind.execute(sa.text("DELETE FROM extfields.field_values WHERE owner_type_code IN ('party', 'contact_person')"))
    bind.execute(sa.text("DELETE FROM extfields.field_definitions WHERE owner_type_code IN ('party', 'contact_person')"))
    bind.execute(sa.text("DELETE FROM core.entity_types WHERE code IN ('party', 'contact_person')"))
    op.execute("DROP SCHEMA IF EXISTS party")
