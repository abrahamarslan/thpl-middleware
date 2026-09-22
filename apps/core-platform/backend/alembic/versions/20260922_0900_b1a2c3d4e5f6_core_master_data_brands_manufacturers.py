"""Core master data — brands, manufacturers, their relations and aliases

Creates the ``core`` schema for shared master data and its six tables:

    entity_types              catalogue of entity types polymorphic refs may name
    brands                    brand master (organization-scoped within a tenant)
    manufacturers             manufacturer master
    brand_manufacturers       brand x manufacturer role + validity window
    manufacturer_identifiers  GSTIN / PAN / CIN / FSSAI / drug licence / …
    entity_aliases            alternative names for any registered entity

Design notes (see app/modules/{entities,brands,manufacturers}/model.py):

  * the hand-rolled columns of the reference design are supplied by the
    repository mixins (OrgEntityMixin / VerificationMixin / DeactivationMixin /
    PolymorphicOwnerMixin / SoftDeleteFilteredMixin / BigIntPKWithUUIDv7Mixin);
  * the reference design's polymorphic ``owner_type``/``owner_id`` FK to
    ``entity_types`` is replaced by ``PolymorphicOwnerMixin`` (a CHECK over the
    closed owner vocabulary, no FK) — the same treatment ``currencies`` uses;
  * cross-organization pairing is prevented structurally by composite FKs
    (``(tenant_id, organization_id, x_id)``), so the reference design's
    ``brand_manufacturer_scope`` / ``manufacturer_child_owner_sync`` triggers are
    not needed;
  * the genuine database guards are kept: a brand-tree cycle guard and a
    no-overlapping-windows constraint trigger, plus the deferred alias-integrity
    trigger (``entity_id`` is polymorphic, so no FK can prove it).

Revision ID: b1a2c3d4e5f6
Revises: 62303d9097fe
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1a2c3d4e5f6"
down_revision: str | None = "62303d9097fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = sa.text("deleted_at IS NULL")

_NAME_NORM = r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))"
_ALIAS_NORM = r"lower(btrim(regexp_replace(alias, '\s+', ' ', 'g')))"
_VALUE_NORM = r"upper(regexp_replace(value, '\s+', '', 'g'))"

_IDENTIFIER_FORMAT = """
    CASE kind
        WHEN 'gstin' THEN value_normalized ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'
        WHEN 'pan'   THEN value_normalized ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
        WHEN 'cin'   THEN value_normalized ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$'
        WHEN 'fssai' THEN value_normalized ~ '^[0-9]{14}$'
        ELSE true
    END
"""


def _uuid_col() -> sa.Column:
    return sa.Column("uuid", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False,
                     comment="Time-ordered public reference id (PG18 uuidv7())")


def _org_audit_columns() -> list[sa.Column]:
    """The OrgEntityMixin bundle (tenant + org + audit + status + row_version + app meta)."""
    return [
        sa.Column("organization_id", sa.BigInteger(), nullable=False,
                  comment="Organization within the tenant (required)"),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Tenant isolation key"),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True,
                  comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True,
                  comment="Last updater display name at the time"),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False,
                  comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(length=32), nullable=True,
                  comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
    ]


def _verification_columns() -> list[sa.Column]:
    return [
        sa.Column("verification_status", sa.String(length=20), server_default=sa.text("'unverified'"),
                  nullable=False, comment="unverified / pending / verified / rejected"),
        sa.Column("verification_method", sa.String(length=50), nullable=True,
                  comment="How it was verified (manual_review, registry_lookup, …)"),
        sa.Column("verification_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Evidence: file refs, provider response ids, signatures"),
        sa.Column("verified_by", sa.BigInteger(), nullable=True, comment="users.id of the verifier (NULL = system)"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _polymorphic_owner_columns() -> list[sa.Column]:
    return [
        sa.Column("owner_type", sa.String(length=50), nullable=False,
                  comment="Owning entity class: tenant / organization / connection / system (CHECK)"),
        sa.Column("owner_id", sa.BigInteger(), nullable=False, comment="Owning entity id (no FK)"),
    ]


def _deactivation_columns() -> list[sa.Column]:
    return [
        sa.Column("deactivation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("deactivated_by", sa.BigInteger(), nullable=True, comment="users.id who deactivated it"),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── entity_types ────────────────────────────────────────────────────────
    op.create_table(
        "entity_types",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("code", sa.String(length=64), nullable=False,
                  comment="Stable registry code, e.g. 'brand', 'manufacturer'"),
        sa.Column("name", sa.Text(), nullable=False, comment="Human-readable label"),
        sa.Column("target_schema", sa.String(length=64), nullable=False,
                  comment="Schema of the table rows of this type live in"),
        sa.Column("target_table", sa.String(length=64), nullable=False,
                  comment="Table rows of this type live in"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_soft_delete_columns(),
        sa.CheckConstraint("btrim(code) <> ''", name="ck_entity_types_code_not_blank"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_entity_types_name_not_blank"),
        sa.CheckConstraint("btrim(target_schema) <> ''", name="ck_entity_types_target_schema_not_blank"),
        sa.CheckConstraint("btrim(target_table) <> ''", name="ck_entity_types_target_table_not_blank"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_entity_types_code"),
        schema="core",
        comment="Catalogue of entity types polymorphic references may name.",
    )
    op.create_index("ix_entity_types_uuid", "entity_types", ["uuid"], unique=True, schema="core")
    op.create_index("ix_entity_types_deleted_at", "entity_types", ["deleted_at"], unique=False, schema="core")

    # ── brands ──────────────────────────────────────────────────────────────
    op.create_table(
        "brands",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("name", sa.Text(), nullable=False, comment="Display/trading name"),
        sa.Column("slug", sa.Text(), nullable=True,
                  comment="URL-friendly identifier, unique per (tenant, organization) among live rows"),
        sa.Column("code", sa.Text(), nullable=True, comment="Short internal code; NULL = unclassified"),
        sa.Column("kind", sa.Text(), nullable=True,
                  comment="own / third_party / private_label; NULL = unclassified"),
        sa.Column("parent_id", sa.BigInteger(), nullable=True,
                  comment="Parent brand (sub-brand); NULL = top-level"),
        sa.Column("name_normalized", sa.Text(),
                  sa.Computed(_NAME_NORM, persisted=True),
                  comment="STORED generated lower-cased, whitespace-collapsed name"),
        sa.Column("country_code", sa.Text(), nullable=True, comment="ISO 3166-1 alpha-2 country code"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("logo_storage_key", sa.Text(), nullable=True,
                  comment="Storage key, never a signed URL (AP18)"),
        *_org_audit_columns(),
        *_polymorphic_owner_columns(),
        *_deactivation_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint("status IN ('active','inactive','discontinued')", name="ck_brands_status"),
        sa.CheckConstraint("kind IS NULL OR kind IN ('own','third_party','private_label')", name="ck_brands_kind"),
        sa.CheckConstraint("owner_type IN ('tenant','organization','connection','system')",
                           name="ck_brands_owner_type"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_brands_name_not_blank"),
        sa.CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_brands_code_not_blank"),
        sa.CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="ck_brands_country_code"),
        sa.CheckConstraint("website_url IS NULL OR website_url ~* '^https?://'", name="ck_brands_website_url"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_brands_no_self_parent"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id", "parent_id"],
                                ["core.brands.tenant_id", "core.brands.organization_id", "core.brands.id"],
                                name="fk_brands_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_brands_scope_id"),
        schema="core",
        comment="Brand master, organization-scoped within a tenant.",
    )
    op.create_index("ix_brands_uuid", "brands", ["uuid"], unique=True, schema="core")
    op.create_index("ix_brands_deleted_at", "brands", ["deleted_at"], unique=False, schema="core")
    op.create_index("ix_brands_status", "brands", ["status"], unique=False, schema="core")
    op.create_index("ix_brands_tenant_id", "brands", ["tenant_id"], unique=False, schema="core")
    op.create_index("ix_brands_tenant_org", "brands", ["tenant_id", "organization_id"], unique=False, schema="core")
    op.create_index("uq_brands_scope_name", "brands", ["tenant_id", "organization_id", "name_normalized"],
                    unique=True, schema="core", postgresql_where=_LIVE)
    op.create_index("uq_brands_scope_code", "brands", ["tenant_id", "organization_id", "code"],
                    unique=True, schema="core", postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("uq_brands_scope_slug", "brands", ["tenant_id", "organization_id", "slug"],
                    unique=True, schema="core", postgresql_where=sa.text("slug IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("ix_brands_owner_scope_name", "brands", ["tenant_id", "organization_id", "name"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_brands_name_trgm", "brands", ["name_normalized"], unique=False, schema="core",
                    postgresql_using="gin", postgresql_ops={"name_normalized": "gin_trgm_ops"},
                    postgresql_where=_LIVE)
    op.create_index("ix_brands_parent_id", "brands", ["parent_id"], unique=False, schema="core",
                    postgresql_where=sa.text("parent_id IS NOT NULL"))

    # ── manufacturers ───────────────────────────────────────────────────────
    op.create_table(
        "manufacturers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("name", sa.Text(), nullable=False, comment="Display/trading name"),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("legal_name", sa.Text(), nullable=True, comment="Registered legal name"),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("name_normalized", sa.Text(), sa.Computed(_NAME_NORM, persisted=True)),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        *_org_audit_columns(),
        *_verification_columns(),
        *_polymorphic_owner_columns(),
        *_deactivation_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint("status IN ('active','inactive','blocked')", name="ck_manufacturers_status"),
        sa.CheckConstraint("owner_type IN ('tenant','organization','connection','system')",
                           name="ck_manufacturers_owner_type"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_manufacturers_name_not_blank"),
        sa.CheckConstraint("legal_name IS NULL OR btrim(legal_name) <> ''",
                           name="ck_manufacturers_legal_name_not_blank"),
        sa.CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_manufacturers_code_not_blank"),
        sa.CheckConstraint("country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
                           name="ck_manufacturers_country_code"),
        sa.CheckConstraint("website_url IS NULL OR website_url ~* '^https?://'",
                           name="ck_manufacturers_website_url"),
        sa.CheckConstraint("verified_at IS NULL OR is_verified IS TRUE", name="ck_manufacturers_verified"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_manufacturers_scope_id"),
        schema="core",
        comment="Manufacturer master (also marketers/importers/principals).",
    )
    op.create_index("ix_manufacturers_uuid", "manufacturers", ["uuid"], unique=True, schema="core")
    op.create_index("ix_manufacturers_deleted_at", "manufacturers", ["deleted_at"], unique=False, schema="core")
    op.create_index("ix_manufacturers_status", "manufacturers", ["status"], unique=False, schema="core")
    op.create_index("ix_manufacturers_verification_status", "manufacturers", ["verification_status"],
                    unique=False, schema="core")
    op.create_index("ix_manufacturers_tenant_id", "manufacturers", ["tenant_id"], unique=False, schema="core")
    op.create_index("ix_manufacturers_tenant_org", "manufacturers", ["tenant_id", "organization_id"],
                    unique=False, schema="core")
    op.create_index("uq_manufacturers_scope_name", "manufacturers",
                    ["tenant_id", "organization_id", "name_normalized"],
                    unique=True, schema="core", postgresql_where=_LIVE)
    op.create_index("uq_manufacturers_scope_code", "manufacturers", ["tenant_id", "organization_id", "code"],
                    unique=True, schema="core", postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("uq_manufacturers_scope_slug", "manufacturers", ["tenant_id", "organization_id", "slug"],
                    unique=True, schema="core", postgresql_where=sa.text("slug IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("ix_manufacturers_owner_scope_name", "manufacturers",
                    ["tenant_id", "organization_id", "name"], unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_manufacturers_name_trgm", "manufacturers", ["name_normalized"], unique=False, schema="core",
                    postgresql_using="gin", postgresql_ops={"name_normalized": "gin_trgm_ops"},
                    postgresql_where=_LIVE)

    # ── brand_manufacturers ─────────────────────────────────────────────────
    op.create_table(
        "brand_manufacturers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("brand_id", sa.BigInteger(), nullable=False, comment="Owning brand"),
        sa.Column("manufacturer_id", sa.BigInteger(), nullable=False, comment="Linked manufacturer"),
        sa.Column("kind", sa.Text(), nullable=True,
                  comment="brand_owner / manufacturer / contract_manufacturer / marketer / importer; NULL = unclassified"),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=True,
                  comment="Default manufacturer for this brand and kind"),
        sa.Column("valid_from", sa.Date(), server_default=sa.text("CURRENT_DATE"), nullable=True,
                  comment="Business date the relation starts; NULL = unbounded past"),
        sa.Column("valid_to", sa.Date(), nullable=True,
                  comment="Half-open [valid_from, valid_to); NULL = still current"),
        *_org_audit_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint(
            "kind IS NULL OR kind IN ('brand_owner','manufacturer','contract_manufacturer','marketer','importer')",
            name="ck_brand_manufacturers_kind"),
        sa.CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                           name="ck_brand_manufacturers_valid_window"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "brand_id"],
            ["core.brands.tenant_id", "core.brands.organization_id", "core.brands.id"],
            name="fk_brand_manufacturers_brand", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "manufacturer_id"],
            ["core.manufacturers.tenant_id", "core.manufacturers.organization_id", "core.manufacturers.id"],
            name="fk_brand_manufacturers_manufacturer", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
        comment="Brand x manufacturer relation with role, default and validity window.",
    )
    op.create_index("ix_brand_manufacturers_uuid", "brand_manufacturers", ["uuid"], unique=True, schema="core")
    op.create_index("ix_brand_manufacturers_deleted_at", "brand_manufacturers", ["deleted_at"],
                    unique=False, schema="core")
    op.create_index("ix_brand_manufacturers_status", "brand_manufacturers", ["status"],
                    unique=False, schema="core")
    op.create_index("ix_brand_manufacturers_tenant_id", "brand_manufacturers", ["tenant_id"],
                    unique=False, schema="core")
    op.create_index("ix_brand_manufacturers_tenant_org", "brand_manufacturers",
                    ["tenant_id", "organization_id"], unique=False, schema="core")
    op.create_index("ix_brand_manufacturers_brand_id", "brand_manufacturers", ["brand_id"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_brand_manufacturers_manufacturer_id", "brand_manufacturers", ["manufacturer_id"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("uq_brand_manufacturers_current", "brand_manufacturers",
                    ["tenant_id", "organization_id", "brand_id", "manufacturer_id", "kind"],
                    unique=True, schema="core",
                    postgresql_where=sa.text("deleted_at IS NULL AND valid_to IS NULL"),
                    postgresql_nulls_not_distinct=True)
    op.create_index("ux_brand_manufacturers_default", "brand_manufacturers",
                    ["tenant_id", "organization_id", "brand_id", "kind"],
                    unique=True, schema="core",
                    postgresql_where=sa.text("is_default IS TRUE AND deleted_at IS NULL AND valid_to IS NULL"),
                    postgresql_nulls_not_distinct=True)

    # ── manufacturer_identifiers ────────────────────────────────────────────
    op.create_table(
        "manufacturer_identifiers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("manufacturer_id", sa.BigInteger(), nullable=False, comment="Owning manufacturer"),
        sa.Column("kind", sa.Text(), nullable=True,
                  comment="gstin / pan / cin / fssai / drug_manufacturing_licence / …; NULL = unclassified"),
        sa.Column("value", sa.Text(), nullable=False, comment="Exactly as received"),
        sa.Column("value_normalized", sa.Text(), sa.Computed(_VALUE_NORM, persisted=True),
                  comment="STORED generated upper-cased, whitespace-free value"),
        sa.Column("issuing_authority", sa.Text(), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        *_org_audit_columns(),
        *_verification_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint(
            "kind IS NULL OR kind IN ('gstin','pan','cin','fssai','drug_manufacturing_licence','who_gmp',"
            "'iso_certificate','gs1_company_prefix','duns','lei','other')",
            name="ck_manufacturer_identifiers_kind"),
        sa.CheckConstraint("btrim(value) <> ''", name="ck_manufacturer_identifiers_value_not_blank"),
        sa.CheckConstraint(_IDENTIFIER_FORMAT.strip(), name="ck_manufacturer_identifiers_format"),
        sa.CheckConstraint("expires_on IS NULL OR issued_on IS NULL OR expires_on > issued_on",
                           name="ck_manufacturer_identifiers_expiry"),
        sa.CheckConstraint("verified_at IS NULL OR is_verified IS TRUE",
                           name="ck_manufacturer_identifiers_verified"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "manufacturer_id"],
            ["core.manufacturers.tenant_id", "core.manufacturers.organization_id", "core.manufacturers.id"],
            name="fk_manufacturer_identifiers_manufacturer", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
        comment="Registrations and licences of a manufacturer.",
    )
    op.create_index("ix_manufacturer_identifiers_uuid", "manufacturer_identifiers", ["uuid"],
                    unique=True, schema="core")
    op.create_index("ix_manufacturer_identifiers_deleted_at", "manufacturer_identifiers", ["deleted_at"],
                    unique=False, schema="core")
    op.create_index("ix_manufacturer_identifiers_status", "manufacturer_identifiers", ["status"],
                    unique=False, schema="core")
    op.create_index("ix_manufacturer_identifiers_verification_status", "manufacturer_identifiers",
                    ["verification_status"], unique=False, schema="core")
    op.create_index("ix_manufacturer_identifiers_tenant_id", "manufacturer_identifiers", ["tenant_id"],
                    unique=False, schema="core")
    op.create_index("ix_manufacturer_identifiers_tenant_org", "manufacturer_identifiers",
                    ["tenant_id", "organization_id"], unique=False, schema="core")
    op.create_index("ix_manufacturer_identifiers_manufacturer_id", "manufacturer_identifiers",
                    ["manufacturer_id"], unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_manufacturer_identifiers_lookup", "manufacturer_identifiers",
                    ["tenant_id", "organization_id", "kind", "value_normalized"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("uq_manufacturer_identifiers_current", "manufacturer_identifiers",
                    ["tenant_id", "organization_id", "manufacturer_id", "kind", "value_normalized"],
                    unique=True, schema="core", postgresql_where=_LIVE,
                    postgresql_nulls_not_distinct=True)

    # ── entity_aliases ──────────────────────────────────────────────────────
    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("entity_type", sa.String(length=64), nullable=False,
                  comment="Registry code from core.entity_types.code"),
        sa.Column("entity_id", sa.BigInteger(), nullable=False,
                  comment="Internal id of the target; no FK possible (polymorphic)"),
        sa.Column("alias", sa.Text(), nullable=False, comment="Exactly as received"),
        sa.Column("alias_normalized", sa.Text(), sa.Computed(_ALIAS_NORM, persisted=True),
                  comment="STORED generated lower-cased alias"),
        sa.Column("kind", sa.Text(), nullable=True,
                  comment="abbreviation / former_name / misspelling / translation / trade_name; NULL = unclassified"),
        sa.Column("language_code", sa.String(length=16), nullable=True, comment="BCP-47 language tag"),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_by_name", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()),
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_soft_delete_columns(),
        sa.CheckConstraint("btrim(alias) <> ''", name="ck_entity_aliases_alias_not_blank"),
        sa.CheckConstraint(
            "kind IS NULL OR kind IN ('abbreviation','former_name','misspelling','translation','trade_name')",
            name="ck_entity_aliases_kind"),
        sa.CheckConstraint(
            "language_code IS NULL OR language_code ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="ck_entity_aliases_language_code"),
        sa.ForeignKeyConstraint(["entity_type"], ["core.entity_types.code"],
                                name="fk_entity_aliases_entity_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
        comment="Alternative names for any registered entity.",
    )
    op.create_index("ix_entity_aliases_uuid", "entity_aliases", ["uuid"], unique=True, schema="core")
    op.create_index("ix_entity_aliases_deleted_at", "entity_aliases", ["deleted_at"], unique=False, schema="core")
    op.create_index("ix_entity_aliases_tenant_id", "entity_aliases", ["tenant_id"], unique=False, schema="core")
    op.create_index("ix_entity_aliases_tenant_org", "entity_aliases", ["tenant_id", "organization_id"],
                    unique=False, schema="core")
    op.create_index("uq_entity_aliases_current", "entity_aliases",
                    ["tenant_id", "entity_type", "entity_id", "alias_normalized"],
                    unique=True, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_entity_aliases_lookup", "entity_aliases",
                    ["tenant_id", "entity_type", "alias_normalized"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_entity_aliases_alias_trgm", "entity_aliases", ["alias_normalized"],
                    unique=False, schema="core", postgresql_using="gin",
                    postgresql_ops={"alias_normalized": "gin_trgm_ops"}, postgresql_where=_LIVE)

    # ── functions & triggers ────────────────────────────────────────────────

    # Prove a polymorphic target exists by resolving the registry row.
    op.execute("""
        CREATE FUNCTION core.assert_entity_exists(p_entity_type text, p_entity_id bigint)
        RETURNS void
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            v_schema text;
            v_table  text;
            v_found  int;
        BEGIN
            SELECT et.target_schema, et.target_table
              INTO v_schema, v_table
              FROM core.entity_types et
             WHERE et.code = p_entity_type
               AND et.deleted_at IS NULL;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'entity type % is not registered', p_entity_type
                    USING ERRCODE = 'foreign_key_violation';
            END IF;

            EXECUTE format('SELECT 1 FROM %I.%I WHERE id = $1', v_schema, v_table)
                INTO v_found USING p_entity_id;

            -- v_found stays NULL when the dynamic query returns no row; do not
            -- rely on FOUND (a preceding SELECT INTO leaves it true).
            IF v_found IS NULL THEN
                RAISE EXCEPTION '% % does not exist', p_entity_type, p_entity_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
        END $$;
    """)

    op.execute("""
        CREATE FUNCTION core.check_entity_alias() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.deleted_at IS NULL THEN
                PERFORM core.assert_entity_exists(NEW.entity_type, NEW.entity_id);
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_entity_aliases_integrity
            AFTER INSERT OR UPDATE OF entity_type, entity_id, deleted_at ON core.entity_aliases
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION core.check_entity_alias();
    """)

    op.execute("""
        CREATE FUNCTION core.find_orphan_entity_aliases()
        RETURNS TABLE (alias_id bigint, orphan_entity_type text, orphan_entity_id bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            r record;
        BEGIN
            FOR r IN SELECT et.code, et.target_schema, et.target_table
                       FROM core.entity_types et
                      WHERE et.deleted_at IS NULL
            LOOP
                RETURN QUERY EXECUTE format(
                    'SELECT a.id, a.entity_type, a.entity_id
                       FROM core.entity_aliases a
                      WHERE a.entity_type = %L
                        AND a.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = a.entity_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)

    # A brand-tree move must not create a cycle, and a parent must share the
    # child's owner (the composite FK proves tenant/organization; this adds the
    # owner pair and the cycle guard).
    op.execute("""
        CREATE FUNCTION core.guard_brand_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            p_type  text;
            p_id    bigint;
            v_cycle boolean;
        BEGIN
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;

            PERFORM pg_advisory_xact_lock(hashtextextended('brand_tree:' || NEW.tenant_id::text, 0));

            SELECT p.owner_type, p.owner_id INTO p_type, p_id
              FROM core.brands p WHERE p.id = NEW.parent_id;
            IF p_id IS NOT NULL
               AND ROW(p_type, p_id) IS DISTINCT FROM ROW(NEW.owner_type, NEW.owner_id) THEN
                RAISE EXCEPTION 'parent brand % belongs to a different owner', NEW.parent_id
                    USING ERRCODE = 'check_violation';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                WITH RECURSIVE anc(id, parent_id) AS (
                    SELECT b.id, b.parent_id FROM core.brands b WHERE b.id = NEW.parent_id
                    UNION
                    SELECT b.id, b.parent_id FROM core.brands b JOIN anc a ON b.id = a.parent_id
                )
                SELECT EXISTS (SELECT 1 FROM anc WHERE id = NEW.id) INTO v_cycle;
                IF v_cycle THEN
                    RAISE EXCEPTION 'moving brand % under % would create a cycle', NEW.id, NEW.parent_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_brands_parent_guard
            BEFORE INSERT OR UPDATE OF parent_id, owner_type, owner_id ON core.brands
            FOR EACH ROW EXECUTE FUNCTION core.guard_brand_parent();
    """)

    # No overlapping validity windows for the same (brand, manufacturer, kind).
    op.execute("""
        CREATE FUNCTION core.check_brand_manufacturer_overlap() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.deleted_at IS NOT NULL THEN
                RETURN NULL;
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('brand_manufacturers:' || NEW.brand_id::text, 0));
            IF EXISTS (
                SELECT 1
                  FROM core.brand_manufacturers x
                 WHERE x.tenant_id = NEW.tenant_id
                   AND x.organization_id = NEW.organization_id
                   AND x.brand_id = NEW.brand_id
                   AND x.manufacturer_id = NEW.manufacturer_id
                   AND x.kind IS NOT DISTINCT FROM NEW.kind
                   AND x.id <> NEW.id
                   AND x.deleted_at IS NULL
                   AND daterange(x.valid_from, x.valid_to) && daterange(NEW.valid_from, NEW.valid_to)
            ) THEN
                RAISE EXCEPTION 'overlapping window for brand % and manufacturer %',
                    NEW.brand_id, NEW.manufacturer_id
                    USING ERRCODE = 'exclusion_violation';
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_brand_manufacturers_overlap
            AFTER INSERT OR UPDATE OF brand_id, manufacturer_id, kind, valid_from, valid_to, deleted_at
            ON core.brand_manufacturers
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION core.check_brand_manufacturer_overlap();
    """)

    # ── seed the registry ───────────────────────────────────────────────────
    op.execute("""
        INSERT INTO core.entity_types (code, name, target_schema, target_table, created_by_name)
        VALUES ('brand', 'Brand', 'core', 'brands', 'system:migration'),
               ('manufacturer', 'Manufacturer', 'core', 'manufacturers', 'system:migration')
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ctrg_brand_manufacturers_overlap ON core.brand_manufacturers")
    op.execute("DROP FUNCTION IF EXISTS core.check_brand_manufacturer_overlap()")
    op.execute("DROP TRIGGER IF EXISTS trg_brands_parent_guard ON core.brands")
    op.execute("DROP FUNCTION IF EXISTS core.guard_brand_parent()")
    op.execute("DROP TRIGGER IF EXISTS ctrg_entity_aliases_integrity ON core.entity_aliases")
    op.execute("DROP FUNCTION IF EXISTS core.check_entity_alias()")
    op.execute("DROP FUNCTION IF EXISTS core.find_orphan_entity_aliases()")
    op.execute("DROP FUNCTION IF EXISTS core.assert_entity_exists(text, bigint)")

    for table in ("entity_aliases", "manufacturer_identifiers", "brand_manufacturers",
                  "manufacturers", "brands", "entity_types"):
        op.drop_table(table, schema="core")
    op.execute("DROP SCHEMA IF EXISTS core")
