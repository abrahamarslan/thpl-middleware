"""tenancy: tenants + organizations + roles; every table scoped to a tenant

docs/tenancy/README.md. In one transaction:

1. schema ``org_management`` with ``tenants`` and ``organizations`` (approved
   DDL + common columns) and public ``roles``;
2. the DEFAULT tenant (``DEFAULT_TENANT_CODE``) and its system roles;
3. the rows of the v1 ``zoho_organizations`` mirror become ROOT legal-entity
   nodes of the default tenant's tree (Zoho columns carried over), then the
   old table is dropped;
4. every ENTITY table gets the full column set, every LEDGER table
   tenant + app metadata; all existing rows are backfilled into the default
   tenant; ``tenant_id`` becomes NOT NULL with FK → tenants (RESTRICT) and the
   composite FK ``(tenant_id, organization_id)`` → organizations;
5. users: ``role_id`` becomes a real (tenant-safe) FK, ``-1`` → NULL;
   deactivation / verification / audit columns;
6. Zoho mirrors: identity index becomes ``(tenant_id, zoho_id)``; Zoho's own
   ``status`` on locations / zoho users is renamed ``zoho_status``; mirror rows
   are attached to the organization node of ``ZOHO_ORGANIZATION_ID``.

The v1 ``tenant_id`` UUID columns (files, favorites, activity_logs) held no
tenant model and are replaced by the BIGINT key.

Irreversible (data is reshaped and ``zoho_organizations`` dropped): restore
from backup to go back.

Revision ID: 7c2e91d4b0a8
Revises: e6e42c16c52e
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c2e91d4b0a8"
down_revision: str | None = "e6e42c16c52e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "org_management"

ENTITY = ["users", "user_profiles", "documents", "files", "media", "tags", "favorites", "emails",
          "zoho_currencies", "zoho_taxes", "zoho_locations", "zoho_users"]
LEDGER = ["activity_logs", "email_events", "email_links", "taggables", "password_reset_tokens",
          "login_otp_tokens", "zoho_sync_events", "zoho_sync_runs", "zoho_sync_cursors", "zoho_quota_days",
          "zoho_queue_logs", "zoho_sync_stats", "zoho_sync_state", "zoho_oauth_credentials"]
SOFT_DELETE = ["user_profiles", "documents", "files", "media", "tags", "favorites", "emails",
               "zoho_currencies", "zoho_taxes", "zoho_locations", "zoho_users"]
DEACTIVATION = ["zoho_currencies", "zoho_taxes"]
V1_UUID_TENANT = ["files", "favorites", "activity_logs"]
MIRRORS = ["zoho_currencies", "zoho_taxes", "zoho_locations", "zoho_users"]

TS = sa.DateTime(timezone=True)


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table: str, column: sa.Column, *, index: str | None = None) -> None:
    if column.name not in _cols(table):
        op.add_column(table, column)
        if index:
            op.create_index(index, table, [column.name])


def _common_columns(table: str, *, entity: bool) -> None:
    _add(table, sa.Column("tenant_id", sa.BigInteger(), nullable=True, comment="Owning tenant (isolation key)"))
    _add(table, sa.Column("organization_id", sa.BigInteger(), nullable=True,
                          comment="Owning organization within the tenant; NULL = tenant-wide"))
    _add(table, sa.Column("app_version", sa.String(32), nullable=True, comment="App version that last wrote the row"))
    _add(table, sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                          server_default=sa.text("'{}'::jsonb")))
    if not entity:
        return
    _add(table, sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"))
    _add(table, sa.Column("created_by_name", sa.String(255), nullable=True, comment="Creator display name at the time"))
    _add(table, sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"))
    _add(table, sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
         index=f"ix_{table}_status")
    _add(table, sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add(table, sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                          comment="Optimistic-lock counter (incremented on every update)"))
    _add(table, sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")))
    _add(table, sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")))


def _tenant_keys(table: str, default_tenant: int) -> None:
    op.execute(sa.text(f"UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL").bindparams(t=default_tenant))
    op.alter_column(table, "tenant_id", nullable=False)
    op.create_foreign_key(f"{table}_tenant_id_fkey", table, "tenants", ["tenant_id"], ["id"],
                          referent_schema=S, ondelete="RESTRICT")
    op.create_foreign_key(f"fk_{table}_tenant_org", table, "organizations", ["tenant_id", "organization_id"],
                          ["tenant_id", "id"], referent_schema=S, ondelete="RESTRICT")
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_tenant_org", table, ["tenant_id", "organization_id"])


def upgrade() -> None:
    from app.core.conf import settings

    bind = op.get_bind()
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {S}")

    # ── 1. tenants ──────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True,
                  comment="Internal fast-join primary key for relational integrity."),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"),
                  comment="Public identifier for API exposure and cross-module polymorphic links."),
        sa.Column("tenant_code", sa.String(50), nullable=False,
                  comment="Human-readable short code (e.g., THPL). Must be unique among active tenants."),
        sa.Column("name", sa.String(255), nullable=False, comment="Full legal or display name."),
        sa.Column("timezone", sa.String(50), nullable=False, server_default=sa.text("'UTC'"),
                  comment="Default operational timezone for the tenant (e.g., Asia/Kolkata)."),
        sa.Column("locale", sa.String(10), nullable=False, server_default=sa.text("'en-US'"),
                  comment="Default locale for formatting and UI translations (e.g., en-US)."),
        sa.Column("primary_contact_email", sa.String(255), nullable=False,
                  comment="Administrative email for critical system and billing alerts."),
        sa.Column("domain", sa.String(255), nullable=True,
                  comment="Optional custom domain for white-labeled routing (e.g., portal.tenant.com)."),
        sa.Column("primary_user_id", sa.BigInteger(), nullable=True,
                  comment="Core admin user who owns this tenant space (soft reference)."),
        sa.Column("custom_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb"), comment="Tenant-specific configuration or unmapped fields."),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                  comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
        sa.UniqueConstraint("uuid", name="uq_tenants_uuid"),
        sa.CheckConstraint("id > 0", name="chk_tenants_id_positive"),
        sa.CheckConstraint("status IN ('trial','active','suspended','cancelled')", name="chk_tenants_status"),
        schema=S,
        comment="The root of the multi-tenant model. All downstream data scopes to these records.",
    )
    op.create_index("uq_tenants_code_active", "tenants", ["tenant_code"], unique=True, schema=S,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_tenants_domain_active", "tenants", ["domain"], unique=True, schema=S,
                    postgresql_where=sa.text("deleted_at IS NULL AND domain IS NOT NULL"))
    op.create_index("ix_org_management_tenants_status", "tenants", ["status"], schema=S)
    op.create_index("ix_org_management_tenants_deleted_at", "tenants", ["deleted_at"], schema=S)

    first_email = bind.execute(sa.text("SELECT email FROM users WHERE deleted_at IS NULL ORDER BY id LIMIT 1")).scalar()
    default_tenant = bind.execute(
        sa.text(f"INSERT INTO {S}.tenants (tenant_code, name, status, primary_contact_email, created_by_name) "
                "VALUES (:code, :name, 'active', :email, 'system:migration') RETURNING id"),
        {"code": settings.DEFAULT_TENANT_CODE, "name": "Default tenant",
         "email": first_email or "admin@localhost"},
    ).scalar()

    # ── 2. organizations ────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True,
                  comment="Internal fast-join primary key for relational integrity."),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"),
                  comment="Public identifier. Use this in API payloads to prevent ID enumeration."),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant. Ensures absolute data isolation."),
        sa.Column("parent_id", sa.BigInteger(), nullable=True,
                  comment="Parent organization in the hierarchy. NULL = root node."),
        sa.Column("org_code", sa.String(50), nullable=False,
                  comment="Human-readable short code. Unique within the tenant."),
        sa.Column("legal_name", sa.String(255), nullable=False,
                  comment="Official registered legal name of the organization or branch."),
        sa.Column("trading_name", sa.String(255), nullable=True, comment="DBA / recognizable display name for UI and reports."),
        sa.Column("org_type", sa.String(20), nullable=False, server_default=sa.text("'legal_entity'"),
                  comment="Structural classification (holding, legal_entity, branch, solo)."),
        sa.Column("hierarchy_path", sa.Text(), nullable=False, server_default=sa.text("'/'"),
                  comment="Materialized path of UUIDs incl. self (/root/child/) for subtree queries."),
        sa.Column("depth", sa.SmallInteger(), nullable=False, server_default=sa.text("0"),
                  comment="Zero-indexed depth in the tree. Root nodes are 0."),
        sa.Column("tax_id", sa.String(50), nullable=True, comment="Legal tax identifier (GSTIN, VAT, EIN …)."),
        sa.Column("currency_id", sa.BigInteger(), nullable=True, comment="Base reporting currency (zoho_currencies.id)."),
        sa.Column("timezone", sa.String(50), nullable=True, comment="Operational IANA timezone, overriding the tenant default."),
        sa.Column("custom_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb"), comment="Organization-specific data (replaces EAV)."),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("website", sa.String(255), nullable=True),
        sa.Column("industry_type", sa.String(100), nullable=True),
        sa.Column("industry_size", sa.String(100), nullable=True),
        sa.Column("is_default_org", sa.Boolean(), nullable=True),
        sa.Column("language_code", sa.String(10), nullable=True),
        sa.Column("time_zone", sa.String(64), nullable=True, comment="Zoho's time zone label (e.g. IST)"),
        sa.Column("date_format", sa.String(50), nullable=True),
        sa.Column("field_separator", sa.String(10), nullable=True),
        sa.Column("fiscal_year_start_month", sa.Integer(), nullable=True,
                  comment="0 = January … 11 = December (Zoho sends a number OR a month name)"),
        sa.Column("tax_group_enabled", sa.Boolean(), nullable=True),
        sa.Column("zoho_id", sa.String(50), nullable=True, comment="Zoho organization_id"),
        sa.Column("account_created_date", sa.Date(), nullable=True),
        sa.Column("is_org_active", sa.Boolean(), nullable=True, comment="Zoho's own active flag"),
        sa.Column("user_role", sa.String(100), nullable=True, comment="Connected user's role in Zoho"),
        sa.Column("user_status", sa.String(50), nullable=True),
        sa.Column("zoho_currency_id", sa.String(50), nullable=True),
        sa.Column("currency_code", sa.String(10), nullable=True),
        sa.Column("currency_symbol", sa.String(10), nullable=True),
        sa.Column("currency_format", sa.String(50), nullable=True),
        sa.Column("price_precision", sa.Integer(), nullable=True),
        sa.Column("address_street1", sa.String(255), nullable=True),
        sa.Column("address_street2", sa.String(255), nullable=True),
        sa.Column("address_city", sa.String(100), nullable=True),
        sa.Column("address_state", sa.String(100), nullable=True),
        sa.Column("address_country", sa.String(100), nullable=True),
        sa.Column("address_zip", sa.String(20), nullable=True),
        # ZohoMirrorMixin
        sa.Column("zoho_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="Full untouched Zoho document"),
        sa.Column("zoho_raw_hash", sa.LargeBinary(), nullable=True,
                  comment="sha256 of zoho_raw minus volatile keys (apply-gate no-op check)"),
        sa.Column("zoho_raw_synced_at", TS, nullable=True),
        sa.Column("zoho_last_modified_time", TS, nullable=True, comment="Zoho version of the stored data (monotonic fence)"),
        sa.Column("synced_at", TS, nullable=True),
        sa.Column("sync_source", sa.String(48), nullable=True,
                  comment="Provenance of zoho_raw: list:<mode> | detail_fetch | nested:<parent> | webhook"),
        sa.Column("sync_version", sa.BigInteger(), nullable=False, server_default=sa.text("0"),
                  comment="Incremented on every applied change"),
        sa.Column("remote_deleted_at", TS, nullable=True, comment="Tombstone evidence: when the sync learned Zoho deleted it"),
        sa.Column("custom_fields", postgresql.HSTORE(text_type=sa.Text()), nullable=True,
                  comment="Zoho custom fields flattened to text (raw array in zoho_raw)"),
        # common columns
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                  comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("deactivation_date", TS, nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("deactivated_by", sa.BigInteger(), nullable=True, comment="users.id who deactivated it"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
        sa.UniqueConstraint("uuid", name="uq_organizations_uuid"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_organizations_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], [f"{S}.tenants.id"], name="fk_organizations_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "parent_id"], [f"{S}.organizations.tenant_id", f"{S}.organizations.id"],
                                name="fk_organizations_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["currency_id"], ["zoho_currencies.id"], name="fk_organizations_currency",
                                ondelete="SET NULL"),
        sa.CheckConstraint("id > 0", name="chk_organizations_id_positive"),
        sa.CheckConstraint("status IN ('active','suspended','archived')", name="chk_org_status"),
        sa.CheckConstraint("org_type IN ('holding','legal_entity','branch','solo')", name="chk_org_type"),
        sa.CheckConstraint("depth >= 0", name="chk_org_depth"),
        sa.CheckConstraint("org_type <> 'solo' OR parent_id IS NULL", name="chk_org_solo_rootless"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="chk_org_not_own_parent"),
        schema=S,
        comment="The legal/hierarchy tree (holding → entities → branches) scoped strictly by tenant.",
    )
    op.create_index("uq_organizations_code_active", "organizations", ["tenant_id", "org_code"], unique=True, schema=S,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_organizations_parent", "organizations", ["tenant_id", "parent_id"], schema=S,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("idx_organizations_path", "organizations", ["tenant_id", "hierarchy_path"], schema=S,
                    postgresql_ops={"hierarchy_path": "text_pattern_ops"})
    op.create_index("idx_organizations_custom_attr", "organizations", ["custom_attributes"], schema=S,
                    postgresql_using="gin")
    op.create_index("uq_organizations_zoho_id_live", "organizations", ["tenant_id", "zoho_id"], unique=True, schema=S,
                    postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))
    for col in ("name", "email", "zoho_id", "status", "deleted_at", "zoho_last_modified_time"):
        op.create_index(f"ix_org_management_organizations_{col}", "organizations", [col], schema=S)

    # v1 zoho_organizations rows → root legal-entity nodes of the default tenant
    if sa.inspect(bind).has_table("zoho_organizations"):
        op.execute(sa.text(f"""
            INSERT INTO {S}.organizations (
                tenant_id, org_code, legal_name, org_type, status, uuid,
                name, contact_name, email, phone, website, industry_type, industry_size, is_default_org,
                language_code, time_zone, date_format, field_separator, fiscal_year_start_month, tax_group_enabled,
                zoho_id, account_created_date, is_org_active, user_role, user_status, zoho_currency_id,
                currency_code, currency_symbol, currency_format, price_precision,
                address_street1, address_street2, address_city, address_state, address_country, address_zip,
                zoho_raw, zoho_raw_hash, zoho_raw_synced_at, zoho_last_modified_time, synced_at, sync_source,
                sync_version, remote_deleted_at, custom_fields, is_verified,
                created_by_name, created_at, updated_at, deleted_at)
            SELECT :t, COALESCE(NULLIF(code, ''), 'ZOHO-' || zoho_id, 'ORG-' || id), COALESCE(name, code, 'ZOHO-' || zoho_id),
                   'legal_entity', 'active', gen_random_uuid(),
                   name, contact_name, email, phone, website, industry_type, industry_size, is_default_org,
                   language_code, time_zone, date_format, field_separator, fiscal_year_start_month, tax_group_enabled,
                   zoho_id, account_created_date, is_org_active, user_role, user_status, currency_id,
                   currency_code, currency_symbol, currency_format, price_precision,
                   address_street1, address_street2, address_city, address_state, address_country, address_zip,
                   zoho_raw, zoho_raw_hash, zoho_raw_synced_at, zoho_last_modified_time, synced_at, sync_source,
                   sync_version, remote_deleted_at, custom_fields, COALESCE(is_verified, false),
                   'system:migration', created_at, updated_at, deleted_at
            FROM zoho_organizations
        """).bindparams(t=default_tenant))
        op.execute(f"UPDATE {S}.organizations SET hierarchy_path = '/' || uuid::text || '/', depth = 0")
        op.drop_table("zoho_organizations")

    # ── 3. roles ────────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, comment="Stable key, e.g. admin, sales_rep"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb"), comment="Permission strings (RBAC, enforced in a later phase)"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                  comment="Seeded role — cannot be deleted or re-coded"),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BigInteger(), nullable=True,
                  comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                  comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", TS, nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        sa.CheckConstraint("status IN ('active','inactive')", name="chk_roles_status"),
    )
    op.create_index("uq_roles_tenant_code_active", "roles", ["tenant_id", "code"], unique=True,
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_roles_status", "roles", ["status"])
    op.create_index("ix_roles_deleted_at", "roles", ["deleted_at"])
    op.create_foreign_key("roles_tenant_id_fkey", "roles", "tenants", ["tenant_id"], ["id"],
                          referent_schema=S, ondelete="RESTRICT")
    op.create_foreign_key("fk_roles_tenant_org", "roles", "organizations", ["tenant_id", "organization_id"],
                          ["tenant_id", "id"], referent_schema=S, ondelete="RESTRICT")
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])
    op.create_index("ix_roles_tenant_org", "roles", ["tenant_id", "organization_id"])
    for code, name, description in (("owner", "Owner", "Owns the tenant; full control"),
                                     ("admin", "Administrator", "Manages organizations, roles and users of the tenant"),
                                     ("member", "Member", "Regular user")):
        op.execute(sa.text(
            "INSERT INTO roles (tenant_id, code, name, description, is_system, created_by_name) "
            "VALUES (:t, :c, :n, :d, true, 'system:migration')"
        ).bindparams(t=default_tenant, c=code, n=name, d=description))

    # ── 4. v1 UUID tenant columns → dropped (re-added as the BIGINT key) ────
    for table in V1_UUID_TENANT:
        if "tenant_id" in _cols(table):
            op.drop_column(table, "tenant_id")                # drops its indexes too

    # ── 5. users specifics ──────────────────────────────────────────────────
    op.execute("UPDATE users SET role_id = NULL WHERE role_id IS NOT NULL AND role_id < 1")
    op.alter_column("users", "role_id", type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=True,
                    server_default=None, comment="roles.id of the user's tenant (composite FK)",
                    existing_comment="Foreign key referencing the roles table")
    _add("users", sa.Column("deactivated_by", sa.BigInteger(), nullable=True, comment="users.id who deactivated the account"))
    _add("users", sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                            comment="Identity verified (KYC / admin check)"))
    _add("users", sa.Column("created_by_name", sa.String(255), nullable=True, comment="Creator display name at the time"))
    _add("users", sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why the account was deleted"))
    _add("users", sa.Column("row_version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                            comment="Optimistic-lock counter (incremented on every update)"))
    _common_columns("users", entity=False)

    # ── 6. mirrors: Zoho's status → zoho_status; identity per tenant ────────
    for table in ("zoho_locations", "zoho_users"):
        if "status" in _cols(table) and "zoho_status" not in _cols(table):
            op.drop_index(f"ix_{table}_status", table_name=table)
            op.alter_column(table, "status", new_column_name="zoho_status")
            op.create_index(f"ix_{table}_zoho_status", table, ["zoho_status"])

    # ── 7. common columns everywhere ────────────────────────────────────────
    for table in ENTITY:
        if table != "users":
            _common_columns(table, entity=True)
    for table in SOFT_DELETE:
        _add(table, sa.Column("deleted_at", TS, nullable=True), index=f"ix_{table}_deleted_at")
        _add(table, sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"))
        _add(table, sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"))
    for table in DEACTIVATION:
        _add(table, sa.Column("deactivation_date", TS, nullable=True))
        _add(table, sa.Column("deactivation_reason", sa.Text(), nullable=True))
        _add(table, sa.Column("deactivated_by", sa.BigInteger(), nullable=True, comment="users.id who deactivated it"))
    for table in LEDGER:
        _common_columns(table, entity=False)

    for table in ["users", *[t for t in ENTITY if t != "users"], *LEDGER]:
        _tenant_keys(table, default_tenant)
    op.create_index("ix_activity_tenant_created", "activity_logs", ["tenant_id", "created_at"])

    op.create_foreign_key("fk_users_tenant_role", "users", "roles", ["tenant_id", "role_id"], ["tenant_id", "id"],
                          ondelete="RESTRICT")

    for table in MIRRORS:
        op.drop_index(f"uq_{table}_zoho_id_live", table_name=table)
        op.create_index(f"uq_{table}_zoho_id_live", table, ["tenant_id", "zoho_id"], unique=True,
                        postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))
        if settings.ZOHO_ORGANIZATION_ID:
            op.execute(sa.text(
                f"UPDATE {table} m SET organization_id = o.id FROM {S}.organizations o "
                "WHERE o.tenant_id = m.tenant_id AND o.zoho_id = :z AND o.deleted_at IS NULL "
                "AND m.organization_id IS NULL"
            ).bindparams(z=settings.ZOHO_ORGANIZATION_ID))


def downgrade() -> None:
    raise NotImplementedError(
        "7c2e91d4b0a8 reshapes data (zoho_organizations → organizations, tenant backfill); "
        "restore the pre-upgrade backup to go back"
    )
