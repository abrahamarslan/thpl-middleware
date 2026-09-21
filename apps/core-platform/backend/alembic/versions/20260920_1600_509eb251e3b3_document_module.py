"""Document module: catalog + logical document + files + links + verification trail.

Replaces the single-owner file table ``documents`` with five tables
(docs/documents/README.md):

    document_types              GLOBAL   the catalog (seeded here)
    documents                   ENTITY   the LOGICAL document
    document_files              ENTITY   its physical files / pages
    document_links              ENTITY   polymorphic pivot: what it belongs to, in what role
    document_verification_logs  LEDGER   immutable trail of status transitions

Every legacy row is migrated, none dropped:

  * one legacy row -> one ``GENERAL`` document + one file + (when it had a numeric
    owner id) one ``attachment`` link. The legacy UUID id is kept as ``documents.uuid``,
    so API ids, activity-log subjects and email attachment references still resolve.
  * ``taggables.taggable_id`` for type 'Document' is re-pointed at the new BigInteger id.
  * legacy owner class names become snake_case (``Email`` -> ``email``, ``BrandOwner`` ->
    ``brand_owner``).
  * ``metadata.is_inline`` / ``content_id`` move to the LINK context; ``metadata.local_path``
    becomes a ``local_disk`` file key.
  * legacy fields with no home in the new design (is_visible, display_order, contains_pii,
    access_permissions, download_count, version / revision / version_history, checksum_md5,
    document_status, the raw metadata, an owner id that was not numeric) are kept under
    ``documents.app_metadata.legacy`` — nothing is lost, nothing is a column.
  * scanned_amount / vendor_name / scanned_receipt_date -> ``documents.ocr_extracted_data``;
    extracted_text / processing_results -> ``document_files.processing_results``.

The copy runs in this transaction and a row-count check aborts the whole migration if any
legacy row failed to arrive.

Downgrade restores the legacy shape: ONE legacy row per FILE (a two-sided document becomes
two rows), the first taking the document's uuid. Documents with no file, KYC metadata,
versions, the catalog and the verification trail have no legacy equivalent and are lost.

Revision ID: 509eb251e3b3
Revises: 1aad2ed925a3
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '509eb251e3b3'
down_revision = '1aad2ed925a3'
branch_labels = None
depends_on = None


def _rename_indexes(table: str, prefix: str) -> None:
    """Rename every index of ``table`` (the primary key included) so the names are free."""
    op.execute(sa.text(
        "DO $$ DECLARE r record; BEGIN "
        "FOR r IN SELECT indexname FROM pg_indexes "
        "WHERE tablename = '" + table + "' AND schemaname = current_schema() LOOP "
        "EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, '" + prefix + "' || r.indexname); "
        "END LOOP; END $$"
    ))


def upgrade() -> None:
    # 1. Move the legacy table aside (and free its index names).
    op.execute("ALTER TABLE documents RENAME TO documents_legacy")
    _rename_indexes("documents_legacy", "legacy_")

    # 2. The new tables.
    op.create_table('document_types',
    sa.Column('code', sa.String(length=64), nullable=False, comment='Stable machine code, e.g. AADHAAR, VEHICLE_INSURANCE, GENERAL'),
    sa.Column('display_name', sa.String(length=150), nullable=False, comment='Human-readable name shown in the app/UI'),
    sa.Column('category', sa.String(length=30), nullable=False, comment='Purpose taxonomy (identity_proof / address_proof / vehicle_compliance / …)'),
    sa.Column('description', sa.Text(), nullable=True, comment='Guidance for uploaders'),
    sa.Column('requires_front_and_back', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='True when both faces must be uploaded (Aadhaar, DL)'),
    sa.Column('has_expiry', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Whether this document carries an expiry date'),
    sa.Column('default_validity_days', sa.Integer(), nullable=True, comment='Pre-fills expiry_date and drives re-verification reminders'),
    sa.Column('allows_full_number_storage', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='False = only the masked / last-4 number may be stored (Aadhaar: UIDAI restricts full numbers to entities running a certified Aadhaar Data Vault)'),
    sa.Column('agent_type_requirement', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment='PersonnelType.value -> "mandatory" | "optional" | "not_applicable"'),
    sa.Column('regulatory_reference', sa.Text(), nullable=True, comment="e.g. 'Motor Vehicles Act 1988 s.3 (commercial DL)'"),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='Order in the checklist / upload UI'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivation_reason', sa.Text(), nullable=True),
    sa.Column('deactivated_by', sa.BigInteger(), nullable=True, comment='users.id who deactivated it'),
    sa.CheckConstraint("category IN ('identity_proof','address_proof','age_proof','bank_proof','employment_proof','vehicle_compliance','banking','employment_record','background_verification','training_compliance','consent_proof','statutory_compliance','entity_proof','medical_proof','photograph','other')", name='chk_document_type_category'),
    sa.CheckConstraint('default_validity_days IS NULL OR default_validity_days > 0', name='chk_document_type_validity_days'),
    sa.PrimaryKeyConstraint('id'),
    comment='Catalog of document kinds (platform-wide reference data).'
    )
    op.create_index(op.f('ix_document_types_category'), 'document_types', ['category'], unique=False)
    op.create_index(op.f('ix_document_types_code'), 'document_types', ['code'], unique=True)
    op.create_table('documents',
    sa.Column('document_type_id', sa.BigInteger(), nullable=False, comment='The logical type (AADHAAR, DRIVING_LICENSE, GENERAL, …)'),
    sa.Column('document_purpose', sa.String(length=30), nullable=False, comment='Denormalised type category, for fast filtering'),
    sa.Column('document_number_masked', sa.String(length=100), nullable=True, comment='Masked / partial number, for search and de-duplication'),
    sa.Column('document_number_full_encrypted', sa.Text(), nullable=True, comment='pgcrypto-encrypted full number. MUST stay NULL when the type has allows_full_number_storage = false (Aadhaar)'),
    sa.Column('issuing_authority', sa.String(length=255), nullable=True, comment='Authority that issued it'),
    sa.Column('issuing_state', sa.String(length=100), nullable=True, comment='State / region that issued it'),
    sa.Column('issued_date', sa.Date(), nullable=True, comment='Issue date printed on the document'),
    sa.Column('expiry_date', sa.Date(), nullable=True, comment='Expiry date printed on the document'),
    sa.Column('verification_status', sa.String(length=30), server_default=sa.text("'pending_upload'"), nullable=False, comment='not_uploaded / pending_upload / uploaded / in_review / verified / rejected / expired / resubmission_required'),
    sa.Column('rejection_reason', sa.Text(), nullable=True, comment='Why the document was rejected'),
    sa.Column('ocr_extracted_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Raw OCR / extraction payload, kept for audit'),
    sa.Column('third_party_verification_provider', sa.String(length=50), nullable=True, comment='karza, idfy, hyperverge, signzy, digilocker, parivahan …'),
    sa.Column('third_party_verification_reference_id', sa.String(length=255), nullable=True, comment='Provider transaction / reference id'),
    sa.Column('third_party_verification_cost_inr', sa.Numeric(precision=8, scale=2), nullable=True, comment='Cost charged by the provider for this verification'),
    sa.Column('version_number', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Increments on each resubmission'),
    sa.Column('is_latest_version', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='True for the current version of its chain'),
    sa.Column('supersedes_document_id', sa.BigInteger(), nullable=True, comment='The previous version this one replaces (composite FK with tenant_id)'),
    sa.Column('resubmission_count', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='How many times this document was resubmitted'),
    sa.Column('is_mandatory', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment="Whether it is mandatory for the owner's role (snapshot of the type requirement)"),
    sa.Column('retention_expiry_date', sa.Date(), nullable=True, comment='DPDP Act 2023 retention: purge / anonymise after this date'),
    sa.Column('uuid', sa.UUID(), nullable=False),
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
    sa.Column('verification_method', sa.String(length=50), nullable=True, comment='How it was verified (geocode, field_visit, utility_bill, otp, …)'),
    sa.Column('verification_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Evidence: file refs, provider response ids, signatures'),
    sa.Column('verified_by', sa.BigInteger(), nullable=True, comment='users.id of the verifier (NULL = system)'),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivation_reason', sa.Text(), nullable=True),
    sa.Column('deactivated_by', sa.BigInteger(), nullable=True, comment='users.id who deactivated it'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("document_purpose IN ('identity_proof','address_proof','age_proof','bank_proof','employment_proof','vehicle_compliance','banking','employment_record','background_verification','training_compliance','consent_proof','statutory_compliance','entity_proof','medical_proof','photograph','other')", name='chk_document_purpose'),
    sa.CheckConstraint("is_verified = (verification_status = 'verified')", name='chk_document_is_verified_cache'),
    sa.CheckConstraint("status IN ('active','suspended','archived')", name='chk_document_status'),
    sa.CheckConstraint("verification_method IS NULL OR verification_method IN ('manual_review','ocr_auto_extract','third_party_api','parivahan_api','aadhaar_offline_ekyc')", name='chk_document_verification_method'),
    sa.CheckConstraint("verification_status IN ('not_uploaded','pending_upload','uploaded','in_review','verified','rejected','expired','resubmission_required')", name='chk_document_verification_status'),
    sa.CheckConstraint('expiry_date IS NULL OR issued_date IS NULL OR expiry_date >= issued_date', name='chk_document_dates'),
    sa.CheckConstraint('resubmission_count >= 0', name='chk_document_resubmission_count'),
    sa.CheckConstraint('supersedes_document_id IS NULL OR supersedes_document_id <> id', name='chk_document_not_own_predecessor'),
    sa.CheckConstraint('version_number >= 1', name='chk_document_version_number'),
    sa.ForeignKeyConstraint(['document_type_id'], ['document_types.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_documents_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'supersedes_document_id'], ['documents.tenant_id', 'documents.id'], name='fk_documents_supersedes', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_documents_tenant_id'),
    comment='Logical document: type, verification, printed metadata, versioning, retention.'
    )
    op.create_index(op.f('ix_documents_deleted_at'), 'documents', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_documents_document_purpose'), 'documents', ['document_purpose'], unique=False)
    op.create_index('ix_documents_expiry', 'documents', ['tenant_id', 'expiry_date'], unique=False, postgresql_where=sa.text('deleted_at IS NULL AND expiry_date IS NOT NULL'))
    op.create_index('ix_documents_retention', 'documents', ['retention_expiry_date'], unique=False, postgresql_where=sa.text('retention_expiry_date IS NOT NULL'))
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)
    op.create_index(op.f('ix_documents_tenant_id'), 'documents', ['tenant_id'], unique=False)
    op.create_index('ix_documents_tenant_org', 'documents', ['tenant_id', 'organization_id'], unique=False)
    op.create_index('ix_documents_type', 'documents', ['tenant_id', 'document_type_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_documents_uuid'), 'documents', ['uuid'], unique=True)
    op.create_index('ix_documents_verification', 'documents', ['tenant_id', 'verification_status'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_documents_verification_status'), 'documents', ['verification_status'], unique=False)
    op.create_index('uq_documents_supersedes', 'documents', ['supersedes_document_id'], unique=True, postgresql_where=sa.text('supersedes_document_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_table('document_files',
    sa.Column('document_id', sa.BigInteger(), nullable=False, comment='The logical document (composite FK with tenant_id)'),
    sa.Column('page_side', sa.String(length=20), server_default=sa.text("'not_applicable'"), nullable=False, comment='front / back / single_page / extra_page / not_applicable'),
    sa.Column('page_index', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='Order within the document (front = 0, back = 1, extras follow)'),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='The display file of the document (one per document)'),
    sa.Column('file_name', sa.String(length=255), nullable=False, comment='Original (client) file name'),
    sa.Column('mime_type', sa.String(length=100), nullable=True, comment='e.g. image/jpeg, application/pdf'),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('file_hash_sha256', sa.String(length=64), nullable=True, comment='sha256 (64 hex) of the bytes: integrity + duplicate-upload detection'),
    sa.Column('file_storage_provider', sa.String(length=20), server_default=sa.text("'s3'"), nullable=False, comment='Object store holding the file'),
    sa.Column('file_key', sa.Text(), nullable=False, comment='Object key / path (local_disk: the path)'),
    sa.Column('storage_bucket', sa.String(length=100), nullable=True),
    sa.Column('storage_region', sa.String(length=50), nullable=True),
    sa.Column('storage_class', sa.String(length=50), nullable=True, comment='e.g. STANDARD'),
    sa.Column('storage_version_id', sa.String(length=100), nullable=True, comment='Object version, when versioned'),
    sa.Column('etag', sa.String(length=100), nullable=True),
    sa.Column('storage_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Provider-specific extras'),
    sa.Column('virus_scanned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('processing_status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('processing_results', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Pipeline output, incl. extracted text'),
    sa.Column('uploaded_by', sa.BigInteger(), nullable=True, comment='users.id who uploaded (NULL = system)'),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_channel', sa.String(length=40), nullable=True, comment='mobile_app / web_portal / admin_upload / field_agent_assisted_upload'),
    sa.Column('zoho_id', sa.String(length=50), nullable=True, comment='Zoho document id (per file)'),
    sa.Column('folder_id', sa.String(length=50), nullable=True),
    sa.Column('folder_name', sa.String(length=255), nullable=True),
    sa.Column('uuid', sa.UUID(), nullable=False),
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
    sa.CheckConstraint("file_key <> ''", name='chk_document_file_key'),
    sa.CheckConstraint("file_storage_provider IN ('s3','gcs','azure_blob','local_disk')", name='chk_document_file_storage_provider'),
    sa.CheckConstraint("page_side IN ('front','back','single_page','extra_page','not_applicable')", name='chk_document_file_page_side'),
    sa.CheckConstraint("processing_status IN ('pending','processing','done','failed')", name='chk_document_file_processing_status'),
    sa.CheckConstraint("source_channel IS NULL OR source_channel IN ('mobile_app','web_portal','admin_upload','field_agent_assisted_upload')", name='chk_document_file_source_channel'),
    sa.CheckConstraint("status IN ('active','suspended','archived')", name='chk_document_file_status'),
    sa.CheckConstraint('file_size_bytes IS NULL OR file_size_bytes >= 0', name='chk_document_file_size'),
    sa.CheckConstraint('page_index >= 0', name='chk_document_file_page_index'),
    sa.ForeignKeyConstraint(['tenant_id', 'document_id'], ['documents.tenant_id', 'documents.id'], name='fk_document_files_tenant_document', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_document_files_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment='Physical files / pages of a logical document.'
    )
    op.create_index(op.f('ix_document_files_deleted_at'), 'document_files', ['deleted_at'], unique=False)
    op.create_index('ix_document_files_document', 'document_files', ['document_id', 'page_side'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_document_files_hash', 'document_files', ['tenant_id', 'file_hash_sha256'], unique=False, postgresql_where=sa.text('deleted_at IS NULL AND file_hash_sha256 IS NOT NULL'))
    op.create_index(op.f('ix_document_files_status'), 'document_files', ['status'], unique=False)
    op.create_index(op.f('ix_document_files_tenant_id'), 'document_files', ['tenant_id'], unique=False)
    op.create_index('ix_document_files_tenant_org', 'document_files', ['tenant_id', 'organization_id'], unique=False)
    op.create_index(op.f('ix_document_files_uuid'), 'document_files', ['uuid'], unique=True)
    op.create_index('uq_document_files_one_primary', 'document_files', ['document_id'], unique=True, postgresql_where=sa.text('is_primary AND deleted_at IS NULL'))
    op.create_index('uq_document_files_side', 'document_files', ['document_id', 'page_side'], unique=True, postgresql_where=sa.text("page_side IN ('front','back') AND deleted_at IS NULL"))
    op.create_index('uq_document_files_zoho_id_live', 'document_files', ['tenant_id', 'zoho_id'], unique=True, postgresql_where=sa.text('deleted_at IS NULL AND zoho_id IS NOT NULL'))
    op.create_table('document_links',
    sa.Column('document_id', sa.BigInteger(), nullable=False, comment='The logical document (composite FK with tenant_id)'),
    sa.Column('linkable_type', sa.String(length=50), nullable=False, comment='WHO: snake_case owner class — user / vehicle / email / …'),
    sa.Column('linkable_id', sa.BigInteger(), nullable=False, comment="The linked entity's internal id (resolve with linkable_type)"),
    sa.Column('link_role', sa.String(length=20), server_default=sa.text("'owner'"), nullable=False, comment='WHAT KIND: owner / attachment / evidence / reference / version_of'),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Primary link among several of the same role'),
    sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='Ordering hint within a role'),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Per-link display hints (badge_label, tile_hint; for email: is_inline / content_id)'),
    sa.Column('uuid', sa.UUID(), nullable=False),
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
    sa.CheckConstraint("link_role IN ('owner','attachment','evidence','reference','version_of')", name='chk_document_link_role'),
    sa.CheckConstraint("status IN ('active','suspended','archived')", name='chk_document_link_status'),
    sa.CheckConstraint('linkable_id > 0', name='chk_document_link_linkable_id'),
    sa.ForeignKeyConstraint(['tenant_id', 'document_id'], ['documents.tenant_id', 'documents.id'], name='fk_document_links_tenant_document', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_document_links_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment='Polymorphic pivot: any entity <-> a logical document, with a role.'
    )
    op.create_index(op.f('ix_document_links_deleted_at'), 'document_links', ['deleted_at'], unique=False)
    op.create_index('ix_document_links_document', 'document_links', ['document_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_document_links_linkable', 'document_links', ['tenant_id', 'linkable_type', 'linkable_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_document_links_status'), 'document_links', ['status'], unique=False)
    op.create_index(op.f('ix_document_links_tenant_id'), 'document_links', ['tenant_id'], unique=False)
    op.create_index('ix_document_links_tenant_org', 'document_links', ['tenant_id', 'organization_id'], unique=False)
    op.create_index(op.f('ix_document_links_uuid'), 'document_links', ['uuid'], unique=True)
    op.create_index('uq_document_links_dedupe', 'document_links', ['document_id', 'linkable_type', 'linkable_id', 'link_role'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_document_links_one_owner', 'document_links', ['document_id'], unique=True, postgresql_where=sa.text("link_role = 'owner' AND deleted_at IS NULL"))
    op.create_table('document_verification_logs',
    sa.Column('document_id', sa.BigInteger(), nullable=False, comment='The document whose status transitioned (composite FK with tenant_id)'),
    sa.Column('primary_link_type', sa.String(length=50), nullable=True, comment="Snapshot of the owner's linkable_type"),
    sa.Column('primary_link_id', sa.BigInteger(), nullable=True, comment="Snapshot of the owner's linkable_id"),
    sa.Column('action', sa.String(length=30), nullable=False, comment='uploaded / resubmitted / in_review / verified / rejected / resubmission_requested / expired / deleted / downloaded'),
    sa.Column('previous_status', sa.String(length=30), nullable=True, comment='Status before the transition'),
    sa.Column('new_status', sa.String(length=30), nullable=True, comment='Status after the transition'),
    sa.Column('actor_type', sa.String(length=30), server_default=sa.text("'staff'"), nullable=False, comment='staff / system / third_party_webhook'),
    sa.Column('performed_by', sa.BigInteger(), nullable=True, comment='users.id of the actor (NULL = system)'),
    sa.Column('performed_by_name', sa.String(length=255), nullable=True, comment='Actor display name at the time (survives the user being erased)'),
    sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='When the transition occurred'),
    sa.Column('remarks', sa.Text(), nullable=True, comment='Free-form notes on the transition'),
    sa.Column('ip_address', sa.String(length=45), nullable=True, comment='IP address of the actor'),
    sa.Column('device_info', sa.String(length=255), nullable=True, comment='Device information of the actor'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint("action IN ('uploaded','resubmitted','in_review','verified','rejected','resubmission_requested','expired','deleted','downloaded')", name='chk_document_log_action'),
    sa.CheckConstraint("actor_type IN ('staff','system','third_party_webhook')", name='chk_document_log_actor_type'),
    sa.CheckConstraint("new_status IS NULL OR new_status IN ('not_uploaded','pending_upload','uploaded','in_review','verified','rejected','expired','resubmission_required')", name='chk_document_log_new_status'),
    sa.CheckConstraint("previous_status IS NULL OR previous_status IN ('not_uploaded','pending_upload','uploaded','in_review','verified','rejected','expired','resubmission_required')", name='chk_document_log_previous_status'),
    sa.ForeignKeyConstraint(['tenant_id', 'document_id'], ['documents.tenant_id', 'documents.id'], name='fk_document_logs_tenant_document', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_document_verification_logs_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    comment='Append-only audit trail of document status transitions.'
    )
    op.create_index('ix_document_logs_document', 'document_verification_logs', ['document_id', 'performed_at'], unique=False)
    op.create_index('ix_document_logs_primary_link', 'document_verification_logs', ['tenant_id', 'primary_link_type', 'primary_link_id'], unique=False)
    op.create_index('ix_document_logs_tenant', 'document_verification_logs', ['tenant_id', 'performed_at'], unique=False)
    op.create_index(op.f('ix_document_verification_logs_tenant_id'), 'document_verification_logs', ['tenant_id'], unique=False)
    op.create_index('ix_document_verification_logs_tenant_org', 'document_verification_logs', ['tenant_id', 'organization_id'], unique=False)

    # 3. The catalog (idempotent; the frozen column set lives in the seeder).
    from app.modules.documents.seed import seed_document_types

    seed_document_types(op.get_bind())

    # 4. Copy every legacy row.
    op.execute(sa.text(_COPY_DOCUMENTS))
    op.execute(sa.text(_COPY_FILES))
    op.execute(sa.text(_COPY_LINKS))
    op.execute(sa.text(_REMAP_TAGS_UP))

    # 5. Nothing may be lost: refuse to continue (rolling everything back) otherwise.
    bind = op.get_bind()
    legacy = bind.execute(sa.text("SELECT count(*) FROM documents_legacy")).scalar()
    documents = bind.execute(sa.text("SELECT count(*) FROM documents")).scalar()
    files = bind.execute(sa.text("SELECT count(*) FROM document_files")).scalar()
    if not (legacy == documents == files):
        raise RuntimeError(
            f"documents migration lost rows: legacy={legacy} documents={documents} files={files}"
        )

    op.drop_table('documents_legacy')


_COPY_DOCUMENTS = r"""
INSERT INTO documents (
    uuid, tenant_id, organization_id, document_type_id, document_purpose, status,
    verification_status, is_verified, verified_at, deactivation_date, deactivation_reason,
    ocr_extracted_data, app_metadata, created_by, created_by_name, updated_by, updated_by_name,
    created_at, updated_at, deleted_at, deleted_by, deleted_reason, app_version, row_version
)
SELECT
    l.id, l.tenant_id, l.organization_id,
    (SELECT id FROM document_types WHERE code = 'GENERAL'), 'other',
    CASE WHEN COALESCE(l.is_blocked, false) THEN 'suspended'
         WHEN l.status IN ('active', 'suspended', 'archived') THEN l.status
         ELSE 'active' END,
    CASE WHEN COALESCE(l.is_verified, false) THEN 'verified' ELSE 'uploaded' END,
    COALESCE(l.is_verified, false),
    CASE WHEN COALESCE(l.is_verified, false) THEN l.updated_at END,
    CASE WHEN l.is_active IS FALSE THEN COALESCE(l.updated_at, now()) END,
    CASE WHEN l.is_active IS FALSE THEN 'Migrated from the legacy documents table: was inactive' END,
    CASE WHEN l.vendor_name IS NOT NULL OR COALESCE(l.scanned_amount, 0) <> 0 OR l.scanned_receipt_date IS NOT NULL
         THEN jsonb_strip_nulls(jsonb_build_object(
             'vendor_name', l.vendor_name,
             'scanned_amount', CASE WHEN COALESCE(l.scanned_amount, 0) <> 0 THEN l.scanned_amount END,
             'scanned_receipt_date', l.scanned_receipt_date)) END,
    COALESCE(l.app_metadata, '{}'::jsonb)
        || CASE WHEN g.legacy = '{}'::jsonb THEN '{}'::jsonb ELSE jsonb_build_object('legacy', g.legacy) END,
    l.created_by, l.created_by_name, l.updated_by, l.updated_by_name,
    l.created_at, l.updated_at, l.deleted_at, l.deleted_by, l.deleted_reason, l.app_version, l.row_version
FROM documents_legacy AS l
CROSS JOIN LATERAL (
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'document_status', l.document_status, 'is_visible', l.is_visible, 'display_order', l.display_order,
        'contains_pii', l.contains_pii, 'access_permissions', l.access_permissions,
        'download_count', l.download_count, 'version', l.version, 'revision', l.revision,
        'version_history', l.version_history, 'checksum_md5', l.checksum_md5, 'metadata', l."metadata",
        'documentable_type', l.documentable_type, 'documentable_id', l.documentable_id)) AS legacy
) AS g
"""

_COPY_FILES = r"""
INSERT INTO document_files (
    uuid, tenant_id, organization_id, document_id, page_side, page_index, is_primary,
    file_name, mime_type, file_size_bytes, file_hash_sha256,
    file_storage_provider, file_key, storage_bucket, storage_region, storage_class, storage_version_id,
    etag, storage_metadata, virus_scanned, processing_status, processing_results,
    uploaded_by, uploaded_at, zoho_id, folder_id, folder_name,
    created_by, created_by_name, updated_by, updated_by_name, created_at, updated_at,
    deleted_at, deleted_by, deleted_reason, app_version
)
SELECT
    gen_random_uuid(), l.tenant_id, l.organization_id, d.id, 'not_applicable', 0, true,
    l.file_name, l.mime_type, l.file_size,
    CASE WHEN l.checksum_sha256 ~* '^[0-9a-f]{64}$' THEN lower(l.checksum_sha256) END,
    CASE WHEN NULLIF(l."metadata"->>'local_path', '') IS NOT NULL THEN 'local_disk' ELSE 's3' END,
    COALESCE(NULLIF(l."metadata"->>'local_path', ''), NULLIF(l.s3_key, ''), 'legacy-missing/' || l.id::text),
    l.s3_bucket, l.s3_region, l.s3_storage_class, l.s3_version_id, l.s3_etag, l.s3_metadata,
    COALESCE(l.virus_scanned, false),
    CASE lower(COALESCE(l.processing_status, ''))
        WHEN 'processing' THEN 'processing'
        WHEN 'done' THEN 'done' WHEN 'completed' THEN 'done' WHEN 'processed' THEN 'done'
        WHEN 'failed' THEN 'failed' WHEN 'error' THEN 'failed'
        ELSE 'pending' END,
    CASE WHEN l.processing_results IS NOT NULL OR l.extracted_text IS NOT NULL
         THEN jsonb_strip_nulls(jsonb_build_object(
             'legacy_results', l.processing_results, 'extracted_text', l.extracted_text)) END,
    CASE WHEN l.uploaded_by_id ~ '^[0-9]{1,18}$' THEN l.uploaded_by_id::bigint END, l.created_at,
    l.zoho_id, l.folder_id, l.folder_name,
    l.created_by, l.created_by_name, l.updated_by, l.updated_by_name, l.created_at, l.updated_at,
    l.deleted_at, l.deleted_by, l.deleted_reason, l.app_version
FROM documents_legacy AS l
JOIN documents AS d ON d.uuid = l.id
"""

_COPY_LINKS = r"""
INSERT INTO document_links (
    uuid, tenant_id, organization_id, document_id, linkable_type, linkable_id, link_role,
    is_primary, sort_order, context, created_by, created_by_name, updated_by, updated_by_name,
    created_at, updated_at, deleted_at, deleted_by, deleted_reason, app_version
)
SELECT
    gen_random_uuid(), l.tenant_id, l.organization_id, d.id,
    lower(regexp_replace(l.documentable_type, '([a-z0-9])([A-Z])', '\1_\2', 'g')),
    CASE WHEN l.documentable_id ~ '^[0-9]{1,18}$' THEN l.documentable_id::bigint END,
    'attachment', false, COALESCE(l.display_order, 0),
    NULLIF(jsonb_strip_nulls(jsonb_build_object(
        'is_inline', l."metadata"->'is_inline', 'content_id', l."metadata"->'content_id')), '{}'::jsonb),
    l.created_by, l.created_by_name, l.updated_by, l.updated_by_name,
    l.created_at, l.updated_at, l.deleted_at, l.deleted_by, l.deleted_reason, l.app_version
FROM documents_legacy AS l
JOIN documents AS d ON d.uuid = l.id
WHERE NULLIF(l.documentable_type, '') IS NOT NULL
  AND l.documentable_id ~ '^[0-9]{1,18}$'
  AND (CASE WHEN l.documentable_id ~ '^[0-9]{1,18}$' THEN l.documentable_id::bigint END) > 0
"""

_REMAP_TAGS_UP = r"""
UPDATE taggables AS t SET taggable_id = d.id::text
FROM documents AS d
WHERE t.taggable_type = 'Document' AND t.taggable_id = d.uuid::text
"""

_REMAP_TAGS_DOWN = r"""
UPDATE taggables AS t SET taggable_id = d.uuid::text
FROM documents_v2 AS d
WHERE t.taggable_type = 'Document' AND t.taggable_id = d.id::text
"""

#: ONE legacy row per FILE; the first file of a document takes the document's uuid
#: (so tags, activity subjects and email references keep resolving).
_RESTORE_LEGACY = r"""
INSERT INTO documents (
    id, documentable_id, documentable_type, file_name, file_type, file_size, mime_type,
    zoho_id, folder_id, folder_name, document_status, is_active, is_verified, is_blocked, is_visible,
    display_order, s3_bucket, s3_key, s3_version_id, s3_region, s3_storage_class, s3_etag, s3_metadata,
    processing_status, processing_results, scanned_amount, vendor_name, scanned_receipt_date, extracted_text,
    checksum_sha256, virus_scanned, uploaded_by_id, "metadata", created_at, updated_at, deleted_at,
    tenant_id, organization_id, app_version, app_metadata, created_by, created_by_name, updated_by,
    status, row_version, deleted_by, deleted_reason, updated_by_name
)
SELECT
    CASE WHEN f.rn = 1 THEN d.uuid ELSE gen_random_uuid() END,
    COALESCE(lnk.linkable_id::text, d.app_metadata->'legacy'->>'documentable_id'),
    COALESCE(replace(initcap(replace(lnk.linkable_type, '_', ' ')), ' ', ''),
             d.app_metadata->'legacy'->>'documentable_type'),
    f.file_name, COALESCE(lower(substring(f.file_name FROM '\.([^.]+)$')), 'bin'),
    COALESCE(f.file_size_bytes, 0)::int, f.mime_type,
    f.zoho_id, f.folder_id, f.folder_name, 'uploaded', d.deactivation_date IS NULL, d.is_verified,
    d.status = 'suspended', true, COALESCE(lnk.sort_order, 0),
    f.storage_bucket, CASE WHEN f.file_storage_provider = 'local_disk' THEN NULL ELSE f.file_key END,
    f.storage_version_id, f.storage_region, f.storage_class, f.etag, f.storage_metadata,
    f.processing_status, f.processing_results->'legacy_results',
    COALESCE(NULLIF(d.ocr_extracted_data->>'scanned_amount', '')::numeric, 0),
    d.ocr_extracted_data->>'vendor_name',
    NULLIF(d.ocr_extracted_data->>'scanned_receipt_date', '')::timestamptz,
    f.processing_results->'extracted_text',
    f.file_hash_sha256, f.virus_scanned, f.uploaded_by::text,
    NULLIF(jsonb_strip_nulls(jsonb_build_object(
        'is_inline', lnk.context->'is_inline', 'content_id', lnk.context->'content_id',
        'local_path', CASE WHEN f.file_storage_provider = 'local_disk' THEN f.file_key END)), '{}'::jsonb),
    f.created_at, f.updated_at, COALESCE(f.deleted_at, d.deleted_at),
    d.tenant_id, d.organization_id, d.app_version, d.app_metadata - 'legacy',
    d.created_by, d.created_by_name, d.updated_by,
    CASE WHEN d.status IN ('active', 'suspended', 'archived') THEN d.status ELSE 'active' END,
    d.row_version, d.deleted_by, d.deleted_reason, d.updated_by_name
FROM documents_v2 AS d
JOIN (
    SELECT df.*, row_number() OVER (PARTITION BY df.document_id ORDER BY df.is_primary DESC, df.page_index, df.id) AS rn
    FROM document_files AS df
) AS f ON f.document_id = d.id
LEFT JOIN LATERAL (
    SELECT dl.linkable_type, dl.linkable_id, dl.sort_order, dl.context
    FROM document_links AS dl WHERE dl.document_id = d.id
    ORDER BY (dl.link_role = 'attachment') DESC, (dl.link_role = 'owner') DESC, dl.id
    LIMIT 1
) AS lnk ON true
"""


def downgrade() -> None:
    # 1. Move the new `documents` aside, then recreate the legacy table.
    op.execute("ALTER TABLE documents RENAME TO documents_v2")
    _rename_indexes("documents_v2", "v2_")

    op.create_table('documents',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('documentable_id', sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    sa.Column('documentable_type', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('file_name', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
    sa.Column('file_type', sa.VARCHAR(length=50), autoincrement=False, nullable=False),
    sa.Column('file_size', sa.INTEGER(), autoincrement=False, nullable=False, comment='Bytes'),
    sa.Column('mime_type', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('zoho_id', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('folder_id', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('folder_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
    sa.Column('document_status', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('is_verified', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('is_blocked', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('is_visible', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('display_order', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('s3_bucket', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('s3_key', sa.VARCHAR(length=500), autoincrement=False, nullable=True),
    sa.Column('s3_version_id', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('s3_region', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('s3_storage_class', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('s3_etag', sa.VARCHAR(length=100), autoincrement=False, nullable=True),
    sa.Column('s3_metadata', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('processing_status', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('processing_results', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('scanned_amount', sa.NUMERIC(precision=15, scale=2), autoincrement=False, nullable=True),
    sa.Column('vendor_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True),
    sa.Column('scanned_receipt_date', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.Column('extracted_text', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('checksum_md5', sa.VARCHAR(length=32), autoincrement=False, nullable=True),
    sa.Column('checksum_sha256', sa.VARCHAR(length=64), autoincrement=False, nullable=True),
    sa.Column('virus_scanned', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('contains_pii', sa.BOOLEAN(), autoincrement=False, nullable=True),
    sa.Column('access_permissions', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('version', sa.VARCHAR(length=20), autoincrement=False, nullable=True),
    sa.Column('revision', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('version_history', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
    sa.Column('download_count', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('uploaded_by_id', sa.VARCHAR(length=50), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
    sa.Column('deleted_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    sa.Column('tenant_id', sa.BIGINT(), autoincrement=False, nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('organization_id', sa.BIGINT(), autoincrement=False, nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('app_version', sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False),
    sa.Column('created_by', sa.BIGINT(), autoincrement=False, nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BIGINT(), autoincrement=False, nullable=True, comment='users.id of the last updater'),
    sa.Column('status', sa.VARCHAR(length=20), server_default=sa.text("'active'::character varying"), autoincrement=False, nullable=False),
    sa.Column('row_version', sa.INTEGER(), server_default=sa.text('1'), autoincrement=False, nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('deleted_by', sa.BIGINT(), autoincrement=False, nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.TEXT(), autoincrement=False, nullable=True, comment='Why it was deleted'),
    sa.Column('updated_by_name', sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment='Last updater display name at the time'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name=op.f('fk_documents_tenant_org'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], name=op.f('documents_tenant_id_fkey'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('documents_pkey'))
    )
    op.create_index(op.f('uq_documents_zoho_id_live'), 'documents', ['zoho_id'], unique=True, postgresql_where='((deleted_at IS NULL) AND (zoho_id IS NOT NULL))')
    op.create_index(op.f('ix_documents_vendor_name'), 'documents', ['vendor_name'], unique=False)
    op.create_index(op.f('ix_documents_tenant_org'), 'documents', ['tenant_id', 'organization_id'], unique=False)
    op.create_index(op.f('ix_documents_tenant_id'), 'documents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'], unique=False)
    op.create_index(op.f('ix_documents_s3_key'), 'documents', ['s3_key'], unique=False)
    op.create_index(op.f('ix_documents_processing_status'), 'documents', ['processing_status'], unique=False)
    op.create_index(op.f('ix_documents_owner'), 'documents', ['documentable_type', 'documentable_id'], unique=False)
    op.create_index(op.f('ix_documents_file_type'), 'documents', ['file_type'], unique=False)
    op.create_index(op.f('ix_documents_file_name'), 'documents', ['file_name'], unique=False)
    op.create_index(op.f('ix_documents_documentable_type'), 'documents', ['documentable_type'], unique=False)
    op.create_index(op.f('ix_documents_documentable_id'), 'documents', ['documentable_id'], unique=False)
    op.create_index(op.f('ix_documents_document_status'), 'documents', ['document_status'], unique=False)

    # 2. Copy back, restore the tag pointers, drop the new tables.
    op.execute(sa.text(_RESTORE_LEGACY))
    op.execute(sa.text(_REMAP_TAGS_DOWN))
    op.drop_table('document_verification_logs')
    op.drop_table('document_links')
    op.drop_table('document_files')
    op.drop_table('documents_v2')
    op.drop_table('document_types')
