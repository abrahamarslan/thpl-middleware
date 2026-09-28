"""Custom fields — the ``extfields`` extensible custom-field engine

Creates the ``extfields`` schema and its three tables:

    data_types         GLOBAL  Zoho custom-field data_type -> storage column (lookup)
    field_definitions  ENTITY  one custom-field definition (Class F)
    field_values       ENTITY  one typed answer per (field, owner)

Design notes (see app/modules/custom_fields/model.py):

  * the reference design's dedicated ``owner_types`` registry is replaced by the
    shared ``core.entity_types`` table: ``owner_type_code`` is a real FK to
    ``core.entity_types.code``, so a new owner class is a registry row, not DDL —
    and the existing ``core.assert_entity_exists()`` proves a polymorphic owner
    instance at COMMIT (deferred constraint trigger);
  * the deferred ``extfields.check_field_value_integrity()`` combines the owner
    existence proof with the cross-table "populated column matches the data
    type" rule a CHECK cannot express;
  * ``extfields.find_orphan_field_values()`` is the scheduled safety net for a
    hard-deleted owner (R7);
  * ``data_types`` is seeded here (open vocabulary, ON CONFLICT DO NOTHING).

Revision ID: cf0e1d2c3b4a
Revises: 3b7f0ae91c46
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cf0e1d2c3b4a"
down_revision: str | None = "3b7f0ae91c46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "extfields"
_LIVE = sa.text("deleted_at IS NULL")

_STORAGE_COLUMNS = "'value_text','value_numeric','value_date','value_boolean','value_json'"
_PII_TYPES = "'non_pii','pii','sensitive_pii'"


def _uuid_col() -> sa.Column:
    return sa.Column("uuid", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False,
                     comment="Time-ordered public reference id (PG18 uuidv7())")


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True,
                  comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True,
                  comment="Last updater display name at the time"),
    ]


def _org_entity_columns() -> list[sa.Column]:
    """The OrgEntityMixin bundle (tenant + org + audit + status + row_version + app meta)."""
    return [
        sa.Column("organization_id", sa.BigInteger(), nullable=False,
                  comment="Organization within the tenant (required)"),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Tenant isolation key"),
        *_audit_columns(),
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


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS extfields")

    # ── data_types (global lookup) ──────────────────────────────────────────
    op.create_table(
        "data_types",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("code", sa.Text(), nullable=False,
                  comment="Zoho data_type code, e.g. 'amount', 'multiselect'"),
        sa.Column("label", sa.Text(), nullable=True, comment="Human-readable label"),
        sa.Column("storage_column", sa.Text(), nullable=False,
                  comment="Which typed column on field_values stores this data type"),
        *_audit_columns(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        *_soft_delete_columns(),
        sa.CheckConstraint(f"storage_column IN ({_STORAGE_COLUMNS})", name="ck_data_types_storage_column"),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
        comment="Zoho custom-field data_type vocabulary mapped to which typed column on field_values "
                "holds it. Global lookup, not CHECK (AP8).",
    )
    op.create_index("ix_data_types_uuid", "data_types", ["uuid"], unique=True, schema=_SCHEMA)
    op.create_index("ix_data_types_deleted_at", "data_types", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("uq_data_types_code", "data_types", ["code"], unique=True, schema=_SCHEMA,
                    postgresql_where=_LIVE)

    # ── field_definitions ───────────────────────────────────────────────────
    op.create_table(
        "field_definitions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("owner_type_code", sa.Text(), nullable=False,
                  comment="Registered entity type (core.entity_types.code)"),
        sa.Column("data_type_id", sa.BigInteger(), nullable=False,
                  comment="Field data type; selects the storage column on field_values"),
        sa.Column("api_name", sa.Text(), nullable=False, comment="Stable machine name, unique per owner type"),
        sa.Column("label", sa.Text(), nullable=False, comment="Human-readable field label"),
        sa.Column("placeholder", sa.Text(), nullable=True, comment="Input placeholder text"),
        sa.Column("help_text", sa.Text(), nullable=True, comment="Helper text shown with the field"),
        sa.Column("default_value", sa.Text(), nullable=True, comment="Default value (text form)"),
        sa.Column("sort_order", sa.Integer(), nullable=True, comment="Display order within the owner type"),
        sa.Column("precision", sa.SmallInteger(), nullable=True, comment="Decimal precision for numeric types"),
        sa.Column("max_length", sa.Integer(), nullable=True, comment="Maximum length for text types"),
        sa.Column("is_mandatory", sa.Boolean(), nullable=True, comment="Field is required"),
        sa.Column("is_mandatory_in_sales_item", sa.Boolean(), nullable=True, comment="Required on sales items"),
        sa.Column("is_mandatory_in_storefront", sa.Boolean(), nullable=True,
                  comment="Required on the storefront"),
        sa.Column("is_mandatory_in_hp", sa.Boolean(), nullable=True, comment="Required on the hosted page"),
        sa.Column("show_in_store", sa.Boolean(), nullable=True, comment="Visible on the storefront"),
        sa.Column("show_in_hp", sa.Boolean(), nullable=True, comment="Visible on the hosted page"),
        sa.Column("show_in_all_pdf", sa.Boolean(), nullable=True, comment="Visible in all generated PDFs"),
        sa.Column("edit_on_store", sa.Boolean(), nullable=True, comment="Editable from the storefront"),
        sa.Column("is_read_only", sa.Boolean(), nullable=True, comment="Read-only (e.g. autonumber)"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True,
                  comment="Field is active; NULL = unspecified"),
        sa.Column("is_dependent_field", sa.Boolean(), nullable=True,
                  comment="Value/visibility depends on another field"),
        sa.Column("depends_on_field_id", sa.BigInteger(), nullable=True,
                  comment="The field this definition depends on (self-reference)"),
        sa.Column("is_inherited_value", sa.Boolean(), nullable=True, comment="Value may be inherited"),
        sa.Column("is_basecurrency_amount", sa.Boolean(), nullable=True,
                  comment="Amount is expressed in the base currency"),
        sa.Column("pii_type", sa.Text(), nullable=True,
                  comment="DPDP classification; drives erasure for every field_values row under this field"),
        *_org_entity_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint(f"pii_type IS NULL OR pii_type IN ({_PII_TYPES})",
                           name="ck_field_definitions_pii_type"),
        sa.CheckConstraint("depends_on_field_id IS NULL OR depends_on_field_id <> id",
                           name="ck_field_definitions_no_self_dependency"),
        sa.CheckConstraint("sort_order IS NULL OR sort_order >= 0", name="ck_field_definitions_sort_order"),
        sa.CheckConstraint("max_length IS NULL OR max_length > 0", name="ck_field_definitions_max_length"),
        sa.CheckConstraint("precision IS NULL OR (precision >= 0 AND precision <= 38)",
                           name="ck_field_definitions_precision"),
        sa.ForeignKeyConstraint(["owner_type_code"], ["core.entity_types.code"],
                                name="fk_field_definitions_owner_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["data_type_id"], [f"{_SCHEMA}.data_types.id"],
                                name="fk_field_definitions_data_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "depends_on_field_id"],
            [f"{_SCHEMA}.field_definitions.tenant_id", f"{_SCHEMA}.field_definitions.organization_id",
             f"{_SCHEMA}.field_definitions.id"],
            name="fk_field_definitions_depends_on", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "id", name="uq_field_definitions_scope_id"),
        sa.UniqueConstraint("tenant_id", "organization_id", "owner_type_code", "id",
                            name="uq_field_definitions_owner_scope_id"),
        schema=_SCHEMA,
        comment="Custom field definitions (Class F). Definition data only; owner_type_code FK to the "
                "shared core.entity_types registry.",
    )
    op.create_index("ix_field_definitions_uuid", "field_definitions", ["uuid"], unique=True, schema=_SCHEMA)
    op.create_index("ix_field_definitions_deleted_at", "field_definitions", ["deleted_at"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_field_definitions_status", "field_definitions", ["status"], unique=False, schema=_SCHEMA)
    op.create_index("ix_field_definitions_tenant_id", "field_definitions", ["tenant_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_field_definitions_tenant_org", "field_definitions", ["tenant_id", "organization_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_field_definitions_owner_type_code", "field_definitions", ["owner_type_code"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_field_definitions_data_type_id", "field_definitions", ["data_type_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("uq_field_definitions_scope_apiname", "field_definitions",
                    ["tenant_id", "organization_id", "owner_type_code", "api_name"],
                    unique=True, schema=_SCHEMA, postgresql_where=_LIVE)
    op.create_index("ix_field_definitions_owner", "field_definitions",
                    ["tenant_id", "organization_id", "owner_type_code"],
                    unique=False, schema=_SCHEMA, postgresql_where=_LIVE)

    # ── field_values ────────────────────────────────────────────────────────
    op.create_table(
        "field_values",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        _uuid_col(),
        sa.Column("field_definition_id", sa.BigInteger(), nullable=False,
                  comment="The field this value answers"),
        sa.Column("owner_type_code", sa.Text(), nullable=False,
                  comment="Registered entity type of the value's owner (core.entity_types.code)"),
        sa.Column("owner_id", sa.BigInteger(), nullable=False,
                  comment="Internal id of the owning entity; polymorphic, no FK possible"),
        sa.Column("value_text", sa.Text(), nullable=True,
                  comment="Text-typed value (text/email/phone/url/dropdown/autonumber/attachment)"),
        sa.Column("value_numeric", sa.Numeric(20, 6), nullable=True,
                  comment="Numeric-typed value (amount/decimal/percent/number)"),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=True,
                  comment="Date/datetime-typed value"),
        sa.Column("value_boolean", sa.Boolean(), nullable=True, comment="Checkbox-typed value"),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="JSON-typed value (multiselect and structured values)"),
        *_org_entity_columns(),
        *_soft_delete_columns(),
        sa.CheckConstraint(
            "num_nonnulls(value_text, value_numeric, value_date, value_boolean, value_json) <= 1",
            name="ck_field_values_single_value"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id", "owner_type_code", "field_definition_id"],
            [f"{_SCHEMA}.field_definitions.tenant_id", f"{_SCHEMA}.field_definitions.organization_id",
             f"{_SCHEMA}.field_definitions.owner_type_code", f"{_SCHEMA}.field_definitions.id"],
            name="fk_field_values_definition", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_type_code"], ["core.entity_types.code"],
                                name="fk_field_values_owner_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
        comment="One custom field answer per owner. owner_id has no real FK (polymorphic tradeoff) -- "
                "integrity via core.entity_types + assert_entity_exists + find_orphan_field_values().",
    )
    op.create_index("ix_field_values_uuid", "field_values", ["uuid"], unique=True, schema=_SCHEMA)
    op.create_index("ix_field_values_deleted_at", "field_values", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_field_values_status", "field_values", ["status"], unique=False, schema=_SCHEMA)
    op.create_index("ix_field_values_tenant_id", "field_values", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index("ix_field_values_tenant_org", "field_values", ["tenant_id", "organization_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("ix_field_values_field_definition_id", "field_values", ["field_definition_id"],
                    unique=False, schema=_SCHEMA)
    op.create_index("uq_field_values_field_owner", "field_values",
                    ["field_definition_id", "owner_type_code", "owner_id"],
                    unique=True, schema=_SCHEMA, postgresql_where=_LIVE)
    op.create_index("ix_field_values_owner", "field_values",
                    ["tenant_id", "organization_id", "owner_type_code", "owner_id"],
                    unique=False, schema=_SCHEMA, postgresql_where=_LIVE)

    # ── functions & triggers ────────────────────────────────────────────────

    # Owner existence (via the shared registry) + the storage-column rule.
    # Deferred so a definition and its first value can be written in one
    # transaction in either order; the lookup sees the committed state.
    op.execute("""
        CREATE FUNCTION extfields.check_field_value_integrity() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_storage   text;
            v_populated text;
        BEGIN
            IF NEW.deleted_at IS NOT NULL THEN
                RETURN NULL;
            END IF;

            -- Proves the polymorphic owner class is registered AND the instance exists.
            PERFORM core.assert_entity_exists(NEW.owner_type_code, NEW.owner_id);

            SELECT dt.storage_column INTO v_storage
              FROM extfields.field_definitions fd
              JOIN extfields.data_types dt ON dt.id = fd.data_type_id
             WHERE fd.id = NEW.field_definition_id;

            v_populated := CASE
                WHEN NEW.value_text    IS NOT NULL THEN 'value_text'
                WHEN NEW.value_numeric IS NOT NULL THEN 'value_numeric'
                WHEN NEW.value_date    IS NOT NULL THEN 'value_date'
                WHEN NEW.value_boolean IS NOT NULL THEN 'value_boolean'
                WHEN NEW.value_json    IS NOT NULL THEN 'value_json'
                ELSE NULL
            END;

            IF v_populated IS NOT NULL AND v_populated IS DISTINCT FROM v_storage THEN
                RAISE EXCEPTION 'field value populates % but its data type expects %',
                    v_populated, v_storage
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ctrg_field_values_integrity
            AFTER INSERT OR UPDATE OF field_definition_id, owner_type_code, owner_id,
                value_text, value_numeric, value_date, value_boolean, value_json, deleted_at
            ON extfields.field_values
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION extfields.check_field_value_integrity();
    """)

    # Scheduled safety net: a hard-deleted owner leaves a dangling value.
    op.execute("""
        CREATE FUNCTION extfields.find_orphan_field_values()
        RETURNS TABLE (value_id bigint, owner_type_code text, owner_id bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            r record;
        BEGIN
            FOR r IN SELECT et.code, et.target_schema, et.target_table
                       FROM core.entity_types et
                      WHERE et.deleted_at IS NULL
            LOOP
                RETURN QUERY EXECUTE format(
                    'SELECT v.id, v.owner_type_code, v.owner_id
                       FROM extfields.field_values v
                      WHERE v.owner_type_code = %L
                        AND v.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = v.owner_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)

    # ── seed the data-type lookup ───────────────────────────────────────────
    from app.modules.custom_fields.seed import seed_data_types

    seed_data_types(op.get_bind())


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS extfields.find_orphan_field_values()")
    op.execute("DROP TRIGGER IF EXISTS ctrg_field_values_integrity ON extfields.field_values")
    op.execute("DROP FUNCTION IF EXISTS extfields.check_field_value_integrity()")

    op.drop_table("field_values", schema=_SCHEMA)
    op.drop_table("field_definitions", schema=_SCHEMA)
    op.drop_table("data_types", schema=_SCHEMA)
    op.execute("DROP SCHEMA IF EXISTS extfields")