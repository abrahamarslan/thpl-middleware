"""Tax assignments — one polymorphic table for "this entity carries these taxes"

Creates, in the existing ``tax`` schema:

    taxable_entity_types   GLOBAL policy — which entity classes may carry taxes,
                           one tax or several per context, exemptions or not
    tax_assignments        polymorphic owner (owner_type_code + owner_id) → a tax
                           component OR an exemption, in an inter/intra ×
                           sales/purchase context; optional frozen snapshot

Integrity is the platform registry's, the same shape as ``core.entity_aliases``,
``extfields.field_values`` and ``core.categorizables``:

  * ``owner_type_code`` FK → ``taxable_entity_types.entity_type_code`` FK →
    ``core.entity_types.code``: the class is registered AND opted in;
  * ``tax.check_tax_assignment_integrity()`` (deferred): the owner exists
    (``core.assert_entity_exists``), belongs to the SAME tenant/organization as the
    assignment (``tax.assert_owner_scope``), the class's policy holds
    (enabled, exemptions, one-vs-many), serialised per owner by an advisory lock;
  * ``tax.guard_frozen_tax_assignment()``: a frozen row cannot change;
  * ``tax.find_orphan_tax_assignments()``: scheduled safety net.

Also here: ``tax.tax_exemptions`` gains ``UNIQUE (tenant_id, id)`` (the target of the
assignment's composite tenant FK), and ``category`` is registered in
``core.entity_types`` and opted in (one tax per context, no exemptions) — the first
consumer (categories carry Zoho's ``category_tax_preferences``). Later entities
call ``app.modules.taxes.registration.register_taxable_entity_type`` from their own
migration; nothing in this schema changes for them.

Downgrade drops the tables, functions and triggers. It leaves the ``category`` row in
``core.entity_types``: ``core.categorizables`` may reference it, and a registry row
is harmless.

Revision ID: 84daf73430b6
Revises: c063729f29c2
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.taxes.registration import register_taxable_entity_type

revision: str = "84daf73430b6"
down_revision: str | None = "c063729f29c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── exemptions: the FK target for a tenant-pinned assignment ──────────────
    op.create_unique_constraint("uq_tax_exemptions_tenant_id", "tax_exemptions", ["tenant_id", "id"], schema="tax")

    # ── taxable_entity_types (global policy) ──────────────────────────────────
    op.create_table(
        "taxable_entity_types",
        sa.Column("entity_type_code", sa.String(length=64), nullable=False,
                  comment="core.entity_types.code — the class must be registered first"),
        sa.Column("allows_multiple", sa.Boolean(), server_default=sa.text("false"), nullable=False,
                  comment="false = at most ONE tax per (owner, inter/intra, sales/purchase) context — Zoho's shape "
                          "for categories, items and contacts; true = several apply together (an invoice line's "
                          "IGST + cess)"),
        sa.Column("allows_exemption", sa.Boolean(), server_default=sa.text("false"), nullable=False,
                  comment="Whether this class may be assigned a tax exemption (items, contacts, lines: yes; "
                          "categories: no)"),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False,
                  comment="false = no NEW assignments for this class; existing rows stay valid"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("uuid", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False,
                  comment="Time-ordered public reference id (PG18 uuidv7())"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True,
                  comment="Last updater display name at the time"),
        sa.Column("app_version", sa.String(length=32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["entity_type_code"], ["core.entity_types.code"],
                                name="fk_taxable_entity_types_entity_type", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type_code", name="uq_taxable_entity_types_code"),
        schema="tax",
        comment="Which entity classes may carry taxes, and under what rule (global).",
    )
    op.create_index(op.f("ix_tax_taxable_entity_types_uuid"), "taxable_entity_types", ["uuid"], unique=True,
                    schema="tax")

    # ── tax_assignments ───────────────────────────────────────────────────────
    op.create_table(
        "tax_assignments",
        sa.Column("owner_type_code", sa.String(length=64), nullable=False,
                  comment="core.entity_types.code of the owning entity, opted in via tax.taxable_entity_types"),
        sa.Column("owner_id", sa.BigInteger(), nullable=False,
                  comment="The owner's internal id; no FK (polymorphic) — proved at COMMIT"),
        sa.Column("tax_component_id", sa.BigInteger(), nullable=True,
                  comment="A tax rate or tax group; NULL for an exemption or while a source's tax is pending"),
        sa.Column("tax_exemption_id", sa.BigInteger(), nullable=True,
                  comment="An exemption instead of a tax (only for classes with allows_exemption)"),
        sa.Column("external_ref", sa.Text(), nullable=True,
                  comment="The source's id for the tax while it is unresolved (tax_component_id NULL); "
                          "the reconcile lane links it"),
        sa.Column("tax_specification", sa.Text(), nullable=True, comment="'inter' / 'intra'; NULL = any"),
        sa.Column("transaction_type", sa.Text(), nullable=True, comment="'sales' / 'purchase'; NULL = both"),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False,
                  comment="Order among the taxes of one owner (several taxes apply in this order)"),
        sa.Column("source_system", sa.String(length=32), nullable=True,
                  comment="NULL = maintained locally; 'zoho' = fed by the sync (read-only through the API)"),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="The tax as it was when the owning document was issued (name, rate, type, group members)"),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Set with snapshot; a frozen row can no longer change"),
        sa.Column("uuid", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False,
                  comment="Time-ordered public reference id (PG18 uuidv7())"),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Tenant isolation key"),
        sa.Column("organization_id", sa.BigInteger(), nullable=False,
                  comment="Organization within the tenant (required)"),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True,
                  comment="Last updater display name at the time"),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False,
                  comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(length=32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
        sa.CheckConstraint("source_system IS NULL OR btrim(source_system) <> ''",
                           name="ck_tax_assignments_source_not_blank"),
        sa.CheckConstraint("tax_specification IS NULL OR tax_specification IN ('inter','intra')",
                           name="ck_tax_assignments_specification"),
        sa.CheckConstraint("transaction_type IS NULL OR transaction_type IN ('sales','purchase')",
                           name="ck_tax_assignments_transaction_type"),
        sa.CheckConstraint("(frozen_at IS NULL) = (snapshot IS NULL)", name="ck_tax_assignments_frozen_pair"),
        sa.CheckConstraint(
            "num_nonnulls(tax_component_id, tax_exemption_id) = 1 "
            "OR (tax_component_id IS NULL AND tax_exemption_id IS NULL "
            "AND external_ref IS NOT NULL AND source_system IS NOT NULL)",
            name="ck_tax_assignments_target"),
        sa.CheckConstraint("owner_id > 0", name="ck_tax_assignments_owner_id"),
        sa.CheckConstraint("position >= 0", name="ck_tax_assignments_position"),
        sa.ForeignKeyConstraint(["owner_type_code"], ["tax.taxable_entity_types.entity_type_code"],
                                name="fk_tax_assignments_owner_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                name="fk_tax_assignments_tenant_org", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "tax_component_id"],
                                ["tax.tax_components.tenant_id", "tax.tax_components.id"],
                                name="fk_tax_assignments_component", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "tax_exemption_id"],
                                ["tax.tax_exemptions.tenant_id", "tax.tax_exemptions.id"],
                                name="fk_tax_assignments_exemption", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tax",
        comment="Polymorphic tax assignment: an owning entity → a tax component or exemption, in a context.",
    )
    op.create_index("ix_tax_assignments_component", "tax_assignments", ["tax_component_id"], unique=False,
                    schema="tax", postgresql_where=sa.text("deleted_at IS NULL AND tax_component_id IS NOT NULL"))
    op.create_index("ix_tax_assignments_exemption", "tax_assignments", ["tax_exemption_id"], unique=False,
                    schema="tax", postgresql_where=sa.text("deleted_at IS NULL AND tax_exemption_id IS NOT NULL"))
    op.create_index("ix_tax_assignments_owner", "tax_assignments", ["owner_type_code", "owner_id"], unique=False,
                    schema="tax", postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_tax_assignments_tenant_org", "tax_assignments", ["tenant_id", "organization_id"],
                    unique=False, schema="tax")
    op.create_index(op.f("ix_tax_tax_assignments_deleted_at"), "tax_assignments", ["deleted_at"], unique=False,
                    schema="tax")
    op.create_index(op.f("ix_tax_tax_assignments_status"), "tax_assignments", ["status"], unique=False, schema="tax")
    op.create_index(op.f("ix_tax_tax_assignments_tenant_id"), "tax_assignments", ["tenant_id"], unique=False,
                    schema="tax")
    op.create_index(op.f("ix_tax_tax_assignments_uuid"), "tax_assignments", ["uuid"], unique=True, schema="tax")
    op.create_index("uq_tax_assignments_component", "tax_assignments",
                    ["owner_type_code", "owner_id", "tax_component_id", "tax_specification", "transaction_type"],
                    unique=True, schema="tax", postgresql_nulls_not_distinct=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND tax_component_id IS NOT NULL"))
    op.create_index("uq_tax_assignments_exemption", "tax_assignments",
                    ["owner_type_code", "owner_id", "tax_exemption_id", "tax_specification", "transaction_type"],
                    unique=True, schema="tax", postgresql_nulls_not_distinct=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND tax_exemption_id IS NOT NULL"))
    op.create_index("uq_tax_assignments_pending", "tax_assignments",
                    ["owner_type_code", "owner_id", "source_system", "external_ref", "tax_specification",
                     "transaction_type"],
                    unique=True, schema="tax", postgresql_nulls_not_distinct=True,
                    postgresql_where=sa.text("deleted_at IS NULL AND tax_component_id IS NULL "
                                             "AND tax_exemption_id IS NULL"))

    # ── functions & triggers ──────────────────────────────────────────────────

    # The owner must share the assignment's tenant and organization. Generic: the
    # owner's table is only known from the registry, so its columns are probed —
    # a class whose table has no organization_id (an organization itself) is
    # checked on the columns it does have.
    op.execute("""
        CREATE FUNCTION tax.assert_owner_scope(p_type text, p_id bigint, p_tenant bigint, p_org bigint)
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
    """)

    op.execute("""
        CREATE FUNCTION tax.check_tax_assignment_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_multiple boolean;
            v_exempt   boolean;
            v_enabled  boolean;
        BEGIN
            IF NEW.deleted_at IS NOT NULL THEN
                RETURN NULL;
            END IF;

            -- One owner's assignments are checked one transaction at a time, so two
            -- concurrent inserts cannot both pass the one-tax-per-context rule.
            PERFORM pg_advisory_xact_lock(
                hashtextextended('tax_assignments:' || NEW.owner_type_code || ':' || NEW.owner_id::text, 0));

            SELECT p.allows_multiple, p.allows_exemption, p.is_enabled
              INTO v_multiple, v_exempt, v_enabled
              FROM tax.taxable_entity_types p
             WHERE p.entity_type_code = NEW.owner_type_code;
            IF NOT v_enabled THEN
                RAISE EXCEPTION 'tax assignments are disabled for entity type %', NEW.owner_type_code
                    USING ERRCODE = 'check_violation';
            END IF;

            PERFORM core.assert_entity_exists(NEW.owner_type_code, NEW.owner_id);
            PERFORM tax.assert_owner_scope(NEW.owner_type_code, NEW.owner_id, NEW.tenant_id, NEW.organization_id);

            IF NEW.tax_exemption_id IS NOT NULL AND NOT v_exempt THEN
                RAISE EXCEPTION 'entity type % cannot carry a tax exemption', NEW.owner_type_code
                    USING ERRCODE = 'check_violation';
            END IF;

            -- One tax (and one exemption) per (owner, inter/intra, sales/purchase) context
            -- for a class that does not allow several.
            IF NOT v_multiple AND EXISTS (
                SELECT 1
                  FROM tax.tax_assignments x
                 WHERE x.id <> NEW.id
                   AND x.deleted_at IS NULL
                   AND x.owner_type_code = NEW.owner_type_code
                   AND x.owner_id = NEW.owner_id
                   AND x.tax_specification IS NOT DISTINCT FROM NEW.tax_specification
                   AND x.transaction_type IS NOT DISTINCT FROM NEW.transaction_type
                   AND (x.tax_exemption_id IS NULL) = (NEW.tax_exemption_id IS NULL)
            ) THEN
                RAISE EXCEPTION '% % already has a % for this context (spec %, transaction %)',
                    NEW.owner_type_code, NEW.owner_id,
                    CASE WHEN NEW.tax_exemption_id IS NULL THEN 'tax' ELSE 'tax exemption' END,
                    COALESCE(NEW.tax_specification, 'any'), COALESCE(NEW.transaction_type, 'any')
                    USING ERRCODE = 'exclusion_violation';
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_tax_assignments_integrity
            AFTER INSERT OR UPDATE OF owner_type_code, owner_id, tax_component_id, tax_exemption_id,
                tax_specification, transaction_type, tenant_id, organization_id, deleted_at
            ON tax.tax_assignments
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION tax.check_tax_assignment_integrity();
    """)

    # A frozen assignment is what an issued document shows: the tax as it was.
    op.execute("""
        CREATE FUNCTION tax.guard_frozen_tax_assignment() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.frozen_at IS NOT NULL AND (
                   NEW.owner_type_code   IS DISTINCT FROM OLD.owner_type_code
                OR NEW.owner_id          IS DISTINCT FROM OLD.owner_id
                OR NEW.tax_component_id  IS DISTINCT FROM OLD.tax_component_id
                OR NEW.tax_exemption_id  IS DISTINCT FROM OLD.tax_exemption_id
                OR NEW.external_ref      IS DISTINCT FROM OLD.external_ref
                OR NEW.tax_specification IS DISTINCT FROM OLD.tax_specification
                OR NEW.transaction_type  IS DISTINCT FROM OLD.transaction_type
                OR NEW.position          IS DISTINCT FROM OLD.position
                OR NEW.source_system     IS DISTINCT FROM OLD.source_system
                OR NEW.snapshot          IS DISTINCT FROM OLD.snapshot
                OR NEW.frozen_at         IS DISTINCT FROM OLD.frozen_at
            ) THEN
                RAISE EXCEPTION 'tax assignment % is frozen (issued %); it can only be soft-deleted',
                    OLD.id, OLD.frozen_at
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_tax_assignments_frozen_guard
            BEFORE UPDATE ON tax.tax_assignments
            FOR EACH ROW EXECUTE FUNCTION tax.guard_frozen_tax_assignment();
    """)

    # Scheduled safety net (the find_orphan_entity_aliases shape): a hard-deleted
    # owner leaves a dangling assignment.
    op.execute("""
        CREATE FUNCTION tax.find_orphan_tax_assignments()
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
                       FROM tax.tax_assignments a
                      WHERE a.owner_type_code = %L
                        AND a.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = a.owner_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)

    # ── the first consumer: categories carry Zoho's category_tax_preferences ──
    register_taxable_entity_type(
        op.get_bind(), code="category", name="Category", target_schema="core", target_table="categories",
        allows_multiple=False, allows_exemption=False,
        description="One tax per inter/intra context (Zoho category_tax_preferences); no exemptions.",
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS tax.find_orphan_tax_assignments()")
    op.execute("DROP TRIGGER IF EXISTS trg_tax_assignments_frozen_guard ON tax.tax_assignments")
    op.execute("DROP FUNCTION IF EXISTS tax.guard_frozen_tax_assignment()")
    op.execute("DROP TRIGGER IF EXISTS ctrg_tax_assignments_integrity ON tax.tax_assignments")
    op.execute("DROP FUNCTION IF EXISTS tax.check_tax_assignment_integrity()")
    op.execute("DROP FUNCTION IF EXISTS tax.assert_owner_scope(text, bigint, bigint, bigint)")
    op.drop_table("tax_assignments", schema="tax")
    op.drop_table("taxable_entity_types", schema="tax")
    op.drop_constraint("uq_tax_exemptions_tenant_id", "tax_exemptions", schema="tax", type_="unique")
