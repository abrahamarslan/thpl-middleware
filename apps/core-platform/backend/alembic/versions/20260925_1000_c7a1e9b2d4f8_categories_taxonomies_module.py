"""Categories & taxonomies — trees, whitelists, polymorphic assignments

Creates four tables in the existing ``core`` schema:

    taxonomies              named category trees (organization-scoped)
    taxonomy_entity_types   per-taxonomy whitelist of categorisable entity types
    categories              tree nodes; Zoho-synced (identity + mirror columns)
    categorizables          polymorphic, temporally-windowed assignments

Design notes (see app/modules/categories/model.py):

  * every table is ``OrgEntityMixin`` (``tenant_id`` / ``organization_id``
    NOT NULL + composite FK to ``org_management.organizations``), so the
    reference design's polymorphic owner pair and its three owner-match
    triggers collapse into structural composite FKs;
  * ``categorizable_type`` is a real FK to the existing
    ``core.entity_types.code``; ``categorizable_id`` is proved at COMMIT by a
    deferred constraint trigger calling the existing
    ``core.assert_entity_exists()`` (the ``check_entity_alias`` shape);
  * ``core.entity_types`` is NOT modified and NOT seeded — registry population
    is a separate change (plan L4);
  * PL/pgSQL lives here (the ``b1a2c3d4e5f6`` pattern); no ``sql/*.sql`` sidecar.

Deviation from the approved DDL: PostgreSQL cannot reference a PARTIAL unique
index from an FK, so ``taxonomy_entity_types`` cannot be the target of the
planned ``categorizables`` whitelist FK while its uniqueness stays partial.
The whitelist is enforced by ``core.check_categorizable_integrity()`` instead
(it already reads ``allows_multiple`` from that table).

Revision ID: c7a1e9b2d4f8
Revises: cf0e1d2c3b4a
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7a1e9b2d4f8"
down_revision: str | None = "cf0e1d2c3b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE = sa.text("deleted_at IS NULL")
_NAME_NORM = r"lower(btrim(regexp_replace(name, '\s+', ' ', 'g')))"


def _uuid_col() -> sa.Column:
    return sa.Column("uuid", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False,
                     comment="Time-ordered public reference id (PG18 uuidv7())")


def _org_audit_columns(*, status_default: str = "'active'") -> list[sa.Column]:
    """The OrgEntityMixin bundle (tenant + org + audit + status + row_version + app meta)."""
    return [
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Tenant isolation key"),
        sa.Column("organization_id", sa.BigInteger(), nullable=False,
                  comment="Organization within the tenant (required)"),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True,
                  comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True,
                  comment="Last updater display name at the time"),
        sa.Column("status", sa.String(length=20), server_default=sa.text(status_default), nullable=False),
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


def _deactivation_columns() -> list[sa.Column]:
    return [
        sa.Column("deactivation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivation_reason", sa.Text(), nullable=True),
        sa.Column("deactivated_by", sa.BigInteger(), nullable=True, comment="users.id who deactivated it"),
    ]


def _zoho_identity_columns() -> list[sa.Column]:
    return [
        sa.Column("zoho_id", sa.String(length=50), nullable=True,
                  comment="Zoho primary key; NULL until first outbound push succeeds"),
        sa.Column("public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=True,
                  comment="Local stable id; correlation reference sent to Zoho"),
    ]


def _zoho_mirror_columns() -> list[sa.Column]:
    return [
        sa.Column("zoho_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Full untouched Zoho document"),
        sa.Column("zoho_raw_hash", sa.LargeBinary(), nullable=True,
                  comment="sha256 of zoho_raw minus volatile keys (apply-gate no-op check)"),
        sa.Column("zoho_raw_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zoho_last_modified_time", sa.DateTime(timezone=True), nullable=True,
                  comment="Zoho version of the stored data (monotonic fence)"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_source", sa.String(length=48), nullable=True,
                  comment="Provenance of zoho_raw: list:<mode> | detail_fetch | nested:<parent> | webhook"),
        sa.Column("sync_version", sa.BigInteger(), server_default=sa.text("0"), nullable=False,
                  comment="Incremented on every applied change"),
        sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Tombstone evidence: when the sync learned Zoho deleted it"),
        sa.Column("custom_fields", postgresql.HSTORE(), nullable=True,
                  comment="Zoho custom fields flattened to text (raw array in zoho_raw)"),
    ]


def _zoho_push_columns() -> list[sa.Column]:
    """ZohoPushableMixin — local→Zoho state (bidirectional capability)."""
    return [
        sa.Column("sync_state", sa.String(length=20), nullable=True,
                  comment="local_only / awaiting_approval / pending / synced / conflict / failed / deleting"),
        sa.Column("pending_command_id", sa.BigInteger(), nullable=True),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_push_error", sa.Text(), nullable=True),
    ]


def _org_fks(table: str) -> list[sa.Constraint]:
    """The two organization-scope FKs every MultiTenantMixin table carries."""
    return [
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
    ]


def _base_indexes(table: str, *, status: bool = True) -> None:
    op.create_index(f"ix_{table}_uuid", table, ["uuid"], unique=True, schema="core")
    op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"], unique=False, schema="core")
    if status:
        op.create_index(f"ix_{table}_status", table, ["status"], unique=False, schema="core")
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], unique=False, schema="core")
    op.create_index(f"ix_{table}_tenant_org", table, ["tenant_id", "organization_id"],
                    unique=False, schema="core")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── taxonomies ──────────────────────────────────────────────────────────
    op.create_table(
        "taxonomies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        *_org_audit_columns(status_default="'draft'"),
        *_soft_delete_columns(),
        sa.Column("slug", sa.Text(), nullable=False, comment="Stable per-organization key"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('draft','active','retired')", name="ck_taxonomies_status"),
        sa.CheckConstraint("btrim(slug) <> ''", name="ck_taxonomies_slug_not_blank"),
        *_org_fks("taxonomies"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "slug", name="uq_taxonomies_id_slug"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomies_scope_id"),
        schema="core",
        comment="Named category tree, organization-scoped.",
    )
    _base_indexes("taxonomies")
    op.create_index("uq_taxonomies_scope_slug", "taxonomies", ["tenant_id", "organization_id", "slug"],
                    unique=True, schema="core", postgresql_where=_LIVE)

    # ── taxonomy_entity_types ───────────────────────────────────────────────
    op.create_table(
        "taxonomy_entity_types",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        *_org_audit_columns(),
        *_soft_delete_columns(),
        sa.Column("taxonomy_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type_code", sa.String(length=64), nullable=False,
                  comment="core.entity_types.code"),
        sa.Column("allows_multiple", sa.Boolean(), nullable=True,
                  comment="NULL = multi-valued (permissive); false = single-valued"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id"],
            ["core.taxonomies.tenant_id", "core.taxonomies.organization_id", "core.taxonomies.id"],
            name="fk_taxonomy_entity_types_taxonomy", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_type_code"], ["core.entity_types.code"],
                                name="fk_taxonomy_entity_types_entity_type", ondelete="RESTRICT"),
        *_org_fks("taxonomy_entity_types"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_taxonomy_entity_types_scope_id"),
        schema="core",
        comment="Per-taxonomy whitelist of categorisable entity types.",
    )
    _base_indexes("taxonomy_entity_types")
    op.create_index("ix_taxonomy_entity_types_taxonomy_id", "taxonomy_entity_types", ["taxonomy_id"],
                    unique=False, schema="core")
    op.create_index("ix_taxonomy_entity_types_entity_type_code", "taxonomy_entity_types", ["entity_type_code"],
                    unique=False, schema="core")
    op.create_index("uq_taxonomy_entity_types_scope", "taxonomy_entity_types",
                    ["taxonomy_id", "entity_type_code"], unique=True, schema="core", postgresql_where=_LIVE)

    # ── categories ──────────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        *_org_audit_columns(),
        *_deactivation_columns(),
        *_zoho_identity_columns(),
        *_zoho_mirror_columns(),
        *_zoho_push_columns(),
        *_soft_delete_columns(),
        # identity / display
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_normalized", sa.Text(), sa.Computed(_NAME_NORM, persisted=True),
                  comment="STORED generated lower-cased name; uniqueness + trigram search"),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("sub_title", sa.Text(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("ondc_category_type", sa.Text(), nullable=True),
        # tree
        sa.Column("taxonomy_id", sa.BigInteger(), nullable=False),
        sa.Column("taxonomy_slug", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("is_root", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_have_children", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("depth", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("_lft", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("_rgt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("menu_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("show_in_menu", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # record_*
        sa.Column("record_order", sa.Integer(), nullable=True),
        sa.Column("record_previous", sa.BigInteger(), nullable=True),
        sa.Column("record_next", sa.BigInteger(), nullable=True),
        sa.Column("record_status", sa.SmallInteger(), server_default=sa.text("0"), nullable=False,
                  comment="-1 deleted / 0 normal / 1 archived (source vocabulary)"),
        sa.Column("record_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("record_notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("noteable_type", sa.String(length=64), nullable=True),
        sa.Column("noteable_id", sa.BigInteger(), nullable=True),
        sa.Column("document_id", sa.BigInteger(), nullable=True),
        sa.Column("documents", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # SEO
        sa.Column("meta_title", sa.Text(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # media / display
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("icon_color", sa.Text(), nullable=True),
        sa.Column("icon_bg_color", sa.Text(), nullable=True),
        sa.Column("icon_bg_image", sa.Text(), nullable=True),
        sa.Column("icon_border_color", sa.Text(), nullable=True),
        sa.Column("preview_image", sa.Text(), nullable=True),
        sa.Column("thumbnail", sa.Text(), nullable=True),
        sa.Column("banner", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True, comment="Stored display cache (L1)"),
        sa.Column("thumbnail_url", sa.Text(), nullable=True, comment="Stored display cache (L1)"),
        sa.Column("banner_url", sa.Text(), nullable=True, comment="Stored display cache (L1)"),
        # flags
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_promoted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_sponsored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_partnered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=True),
        sa.Column("is_bookmarked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        # buckets
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extra_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_categories_status"),
        sa.CheckConstraint("NOT (is_root AND parent_id IS NOT NULL)", name="ck_categories_root_no_parent"),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_categories_no_self_parent"),
        sa.CheckConstraint("_rgt >= _lft", name="ck_categories_nested_set_bounds"),
        sa.CheckConstraint("depth >= 0", name="ck_categories_depth_nonneg"),
        sa.CheckConstraint("record_status IN (-1, 0, 1)", name="ck_categories_record_status"),
        sa.CheckConstraint("position >= 0", name="ck_categories_position_nonneg"),
        sa.CheckConstraint("display_order >= 0", name="ck_categories_display_order_nonneg"),
        sa.CheckConstraint("menu_order >= 0", name="ck_categories_menu_order_nonneg"),
        sa.CheckConstraint("num_nulls(noteable_type, noteable_id) IN (0, 2)", name="ck_categories_noteable_pair"),
        sa.CheckConstraint("code IS NULL OR btrim(code) <> ''", name="ck_categories_code_not_blank"),
        sa.CheckConstraint("slug IS NULL OR btrim(slug) <> ''", name="ck_categories_slug_not_blank"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id"],
            ["core.taxonomies.tenant_id", "core.taxonomies.organization_id", "core.taxonomies.id"],
            name="fk_categories_taxonomy_scope", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["taxonomy_id", "taxonomy_slug"],
            ["core.taxonomies.id", "core.taxonomies.slug"],
            name="fk_categories_taxonomy_slug", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(
            ["taxonomy_id", "parent_id"],
            ["core.categories.taxonomy_id", "core.categories.id"],
            name="fk_categories_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "parent_id"],
            ["core.categories.tenant_id", "core.categories.organization_id", "core.categories.id"],
            name="fk_categories_parent_scope", ondelete="RESTRICT"),
        *_org_fks("categories"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("taxonomy_id", "id", name="uq_categories_taxonomy_id_id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_categories_scope_id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "taxonomy_id", "id",
                            name="uq_categories_scope_taxonomy_id"),
        schema="core",
        comment="Category tree node (nested-set bounds maintained app-side); Zoho-synced.",
    )
    _base_indexes("categories")
    op.create_index("ix_categories_zoho_id", "categories", ["zoho_id"], unique=False, schema="core")
    op.create_index("ix_categories_public_id", "categories", ["public_id"], unique=True, schema="core")
    op.create_index("ix_categories_zoho_last_modified_time", "categories", ["zoho_last_modified_time"],
                    unique=False, schema="core")
    op.create_index("ix_categories_taxonomy_id", "categories", ["taxonomy_id"], unique=False, schema="core")
    op.create_index("ix_categories_parent_position", "categories", ["parent_id", "position"],
                    unique=False, schema="core")
    op.create_index("ix_categories_sync_state", "categories", ["sync_state"], unique=False, schema="core")
    op.create_index("ix_categories_is_active", "categories", ["is_active"], unique=False, schema="core")
    op.create_index("ix_categories_scope_lft_rgt", "categories",
                    ["tenant_id", "organization_id", "taxonomy_id", "_lft", "_rgt"],
                    unique=False, schema="core", postgresql_where=_LIVE)
    op.create_index("ix_categories_name_trgm", "categories", ["name_normalized"], unique=False, schema="core",
                    postgresql_using="gin", postgresql_ops={"name_normalized": "gin_trgm_ops"},
                    postgresql_where=_LIVE)
    op.create_index("uq_categories_zoho_id_live", "categories", ["zoho_id"], unique=True, schema="core",
                    postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))
    op.create_index("uq_categories_scope_code", "categories",
                    ["tenant_id", "organization_id", "taxonomy_id", "code"],
                    unique=True, schema="core",
                    postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"))
    op.create_index("uq_categories_scope_slug", "categories",
                    ["tenant_id", "organization_id", "taxonomy_id", "slug"],
                    unique=True, schema="core",
                    postgresql_where=sa.text("slug IS NOT NULL AND deleted_at IS NULL"))

    # ── categorizables ──────────────────────────────────────────────────────
    op.create_table(
        "categorizables",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        *_org_audit_columns(),
        *_soft_delete_columns(),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("taxonomy_id", sa.BigInteger(), nullable=False,
                  comment="Derived from the category by a BEFORE INSERT trigger"),
        sa.Column("categorizable_type", sa.String(length=64), nullable=False,
                  comment="core.entity_types.code"),
        sa.Column("categorizable_id", sa.BigInteger(), nullable=False,
                  comment="Internal id; proved at COMMIT by trigger"),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
                           name="ck_categorizables_valid_window"),
        sa.CheckConstraint("sort_order >= 0", name="ck_categorizables_sort_order"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "taxonomy_id", "category_id"],
            ["core.categories.tenant_id", "core.categories.organization_id",
             "core.categories.taxonomy_id", "core.categories.id"],
            name="fk_categorizables_category", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["categorizable_type"], ["core.entity_types.code"],
                                name="fk_categorizables_entity_type", ondelete="RESTRICT"),
        *_org_fks("categorizables"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
        comment="Polymorphic assignment of a thing to a category, with validity window.",
    )
    _base_indexes("categorizables")
    op.create_index("ix_categorizables_categorizable_type", "categorizables", ["categorizable_type"],
                    unique=False, schema="core")
    op.create_index("ix_categorizables_category_sort", "categorizables", ["category_id", "sort_order"],
                    unique=False, schema="core")
    op.create_index("ix_categorizables_thing", "categorizables",
                    ["categorizable_type", "categorizable_id"], unique=False, schema="core",
                    postgresql_where=_LIVE)
    op.create_index("ix_categorizables_taxonomy_type", "categorizables",
                    ["taxonomy_id", "categorizable_type"], unique=False, schema="core")
    op.create_index("uq_categorizables_category_thing", "categorizables",
                    ["category_id", "categorizable_type", "categorizable_id"], unique=True, schema="core",
                    postgresql_where=sa.text("deleted_at IS NULL AND valid_to IS NULL"))
    op.create_index("uq_categorizables_one_primary", "categorizables",
                    ["taxonomy_id", "categorizable_type", "categorizable_id"], unique=True, schema="core",
                    postgresql_where=sa.text("is_primary IS TRUE AND deleted_at IS NULL AND valid_to IS NULL"))

    # ── functions & triggers ────────────────────────────────────────────────

    # A populated taxonomy cannot change organization; the composite scope FKs
    # on categories are the hard backstop, this raises a readable error first.
    op.execute("""
        CREATE FUNCTION core.guard_taxonomy_organization_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               AND EXISTS (SELECT 1 FROM core.categories c WHERE c.taxonomy_id = OLD.id) THEN
                RAISE EXCEPTION 'taxonomy % has categories; its organization cannot change', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_taxonomies_organization_guard
            BEFORE UPDATE OF organization_id ON core.taxonomies
            FOR EACH ROW EXECUTE FUNCTION core.guard_taxonomy_organization_change();
    """)

    # The cross-row category rules the composite FKs cannot express: a parent
    # must be allowed children, and a move must not create a cycle.
    op.execute("""
        CREATE FUNCTION core.guard_category_scope() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_ok    boolean;
            v_cycle boolean;
        BEGIN
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;

            PERFORM pg_advisory_xact_lock(
                hashtextextended('category_tree:' || NEW.tenant_id::text || ':' || NEW.taxonomy_id::text, 0));

            SELECT p.can_have_children INTO v_ok
              FROM core.categories p WHERE p.id = NEW.parent_id;
            IF v_ok IS FALSE THEN
                RAISE EXCEPTION 'category % cannot have children', NEW.parent_id
                    USING ERRCODE = 'check_violation';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                WITH RECURSIVE anc(id, parent_id) AS (
                    SELECT c.id, c.parent_id FROM core.categories c WHERE c.id = NEW.parent_id
                    UNION
                    SELECT c.id, c.parent_id FROM core.categories c JOIN anc a ON c.id = a.parent_id
                )
                SELECT EXISTS (SELECT 1 FROM anc WHERE id = NEW.id) INTO v_cycle;
                IF v_cycle THEN
                    RAISE EXCEPTION 'moving category % under % would create a cycle', NEW.id, NEW.parent_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_categories_scope_guard
            BEFORE INSERT OR UPDATE OF parent_id, taxonomy_id ON core.categories
            FOR EACH ROW EXECUTE FUNCTION core.guard_category_scope();
    """)

    # Synced categories arrive with no taxonomy: the adapter's synchronous
    # pre_upsert hook has no DB access, so the per-organization "zoho" taxonomy
    # is provisioned here, before the NOT NULL / composite-FK checks. The
    # trigger sorts ahead of the scope guard ('d' < 's'), which needs a
    # non-NULL taxonomy_id for its advisory-lock key.
    op.execute("""
        CREATE FUNCTION core.fill_category_default_taxonomy() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_tax_id bigint;
        BEGIN
            IF NEW.taxonomy_id IS NOT NULL THEN
                RETURN NEW;
            END IF;
            SELECT t.id INTO v_tax_id
              FROM core.taxonomies t
             WHERE t.tenant_id = NEW.tenant_id
               AND t.organization_id = NEW.organization_id
               AND t.slug = 'zoho'
               AND t.deleted_at IS NULL
             LIMIT 1;
            IF v_tax_id IS NULL THEN
                INSERT INTO core.taxonomies
                    (tenant_id, organization_id, slug, name, status, is_verified, row_version,
                     app_metadata, created_at, updated_at)
                VALUES
                    (NEW.tenant_id, NEW.organization_id, 'zoho', 'Zoho', 'active', false, 1,
                     '{}'::jsonb, now(), now())
                ON CONFLICT DO NOTHING;
                SELECT t.id INTO v_tax_id
                  FROM core.taxonomies t
                 WHERE t.tenant_id = NEW.tenant_id
                   AND t.organization_id = NEW.organization_id
                   AND t.slug = 'zoho'
                   AND t.deleted_at IS NULL
                 LIMIT 1;
            END IF;
            NEW.taxonomy_id := v_tax_id;
            NEW.taxonomy_slug := 'zoho';
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_categories_default_taxonomy
            BEFORE INSERT ON core.categories
            FOR EACH ROW EXECUTE FUNCTION core.fill_category_default_taxonomy();
    """)

    # Derive the assignment's taxonomy from its category (the only NOT NULL
    # without a natural default); the 4-column FK pins category + taxonomy.
    op.execute("""
        CREATE FUNCTION core.fill_categorizable_defaults() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            c_tax bigint;
        BEGIN
            SELECT c.taxonomy_id INTO c_tax
              FROM core.categories c
             WHERE c.id = NEW.category_id
               AND c.deleted_at IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'category % does not exist', NEW.category_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            NEW.taxonomy_id := COALESCE(NEW.taxonomy_id, c_tax);
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_categorizables_fill_defaults
            BEFORE INSERT ON core.categorizables
            FOR EACH ROW EXECUTE FUNCTION core.fill_categorizable_defaults();
    """)

    # The genuinely polymorphic guard: the target exists, its type is
    # whitelisted for the taxonomy, and no window overlaps another live
    # assignment of the same thing. Deferred, so a replace-set may
    # delete-then-insert in one transaction.
    op.execute("""
        CREATE FUNCTION core.check_categorizable_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_allows      boolean;
            v_multi       boolean;
        BEGIN
            IF NEW.deleted_at IS NOT NULL THEN
                RETURN NULL;
            END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('categorizables:' || NEW.categorizable_type
                                 || ':' || NEW.categorizable_id::text, 0));
            PERFORM core.assert_entity_exists(NEW.categorizable_type, NEW.categorizable_id);

            SELECT tet.allows_multiple INTO v_allows
              FROM core.taxonomy_entity_types tet
             WHERE tet.taxonomy_id = NEW.taxonomy_id
               AND tet.entity_type_code = NEW.categorizable_type
               AND tet.deleted_at IS NULL;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'entity type % is not whitelisted for taxonomy %',
                    NEW.categorizable_type, NEW.taxonomy_id
                    USING ERRCODE = 'foreign_key_violation';
            END IF;
            v_multi := (v_allows IS DISTINCT FROM false);

            IF EXISTS (
                SELECT 1
                  FROM core.categorizables x
                 WHERE x.tenant_id = NEW.tenant_id
                   AND x.id <> NEW.id
                   AND x.deleted_at IS NULL
                   AND x.categorizable_type = NEW.categorizable_type
                   AND x.categorizable_id = NEW.categorizable_id
                   AND (x.category_id = NEW.category_id
                        OR (NOT v_multi AND x.taxonomy_id = NEW.taxonomy_id))
                   AND tstzrange(x.valid_from, x.valid_to) && tstzrange(NEW.valid_from, NEW.valid_to)
            ) THEN
                RAISE EXCEPTION 'overlapping assignment for category % / taxonomy %',
                    NEW.category_id, NEW.taxonomy_id
                    USING ERRCODE = 'exclusion_violation';
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_categorizables_integrity
            AFTER INSERT OR UPDATE OF category_id, taxonomy_id, categorizable_type,
                categorizable_id, valid_from, valid_to, deleted_at
            ON core.categorizables
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION core.check_categorizable_integrity();
    """)

    # Scheduled safety net (the find_orphan_entity_aliases shape).
    op.execute("""
        CREATE FUNCTION core.find_orphan_categorizables()
        RETURNS TABLE (link_id bigint, orphan_type text, orphan_id bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            r record;
        BEGIN
            FOR r IN SELECT et.code, et.target_schema, et.target_table
                       FROM core.entity_types et
                      WHERE et.deleted_at IS NULL
            LOOP
                RETURN QUERY EXECUTE format(
                    'SELECT l.id, l.categorizable_type, l.categorizable_id
                       FROM core.categorizables l
                      WHERE l.categorizable_type = %L
                        AND l.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = l.categorizable_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS core.find_orphan_categorizables()")
    op.execute("DROP TRIGGER IF EXISTS ctrg_categorizables_integrity ON core.categorizables")
    op.execute("DROP FUNCTION IF EXISTS core.check_categorizable_integrity()")
    op.execute("DROP TRIGGER IF EXISTS trg_categorizables_fill_defaults ON core.categorizables")
    op.execute("DROP FUNCTION IF EXISTS core.fill_categorizable_defaults()")
    op.execute("DROP TRIGGER IF EXISTS trg_categories_default_taxonomy ON core.categories")
    op.execute("DROP FUNCTION IF EXISTS core.fill_category_default_taxonomy()")
    op.execute("DROP TRIGGER IF EXISTS trg_categories_scope_guard ON core.categories")
    op.execute("DROP FUNCTION IF EXISTS core.guard_category_scope()")
    op.execute("DROP TRIGGER IF EXISTS trg_taxonomies_organization_guard ON core.taxonomies")
    op.execute("DROP FUNCTION IF EXISTS core.guard_taxonomy_organization_change()")

    for table in ("categorizables", "categories", "taxonomy_entity_types", "taxonomies"):
        op.drop_table(table, schema="core")
