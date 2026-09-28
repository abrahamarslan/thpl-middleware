"""Comments module — polymorphic comments on any registered entity.

    CommentableEntityType (comments.commentable_entity_types)  GLOBAL  opt-in policy,
        the ``tax.taxable_entity_types`` shape: which ``core.entity_types`` classes may
        carry comments. Written by the owning module's migration
        (``comments.registration.register_commentable_entity_type``); no write API.
    Comment (comments.comments)  ENTITY  the polymorphic row: an owner (``owner_type`` +
        ``owner_id``) says something, at an instant, in one organization.

Unlike ``core.entity_aliases`` / ``tax.tax_assignments`` / ``extfields.field_values``,
``owner_id`` has NO deferred existence-proving trigger (no ``core.assert_entity_exists`` /
``assert_owner_scope`` call here) — a deliberate simplification: comments are high-volume,
low-stakes, and read-mostly, and the app layer (``comments.service.create_comment``, which
DOES check ``comments.commentable_entity_types.is_active`` before writing) is judged enough.
``owner_type`` keeps its real FK to ``core.entity_types.code`` (the class must at least be
REGISTERED), and ``comments.find_orphan_comments()`` stays as the scheduled safety net for
the one thing that check no longer catches at write time: an owner hard-deleted later.

The first (and, for now, only) registered consumer is ``user`` — see ``app/modules/users/
model.py``'s ``HasCommentsMixin``. Any other module opts in with the same one call; nothing
in this schema changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.comments.registration import register_commentable_entity_type

revision: str = "f3a1b6c9d2e7"
down_revision: str | None = "807ccba816ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS comments")
    op.execute(
        "COMMENT ON SCHEMA comments IS "
        "'Comment/activity-trail entities, synced from Zoho or authored in-app, attached "
        "polymorphically to any registered core.entity_types class.'"
    )

    # ── commentable_entity_types (global policy) ───────────────────────────────
    op.create_table(
        "commentable_entity_types",
        sa.Column("entity_type_code", sa.Text(), nullable=False,
                  comment="core.entity_types.code — the class must be registered first"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False,
                  comment="false = no NEW comments for this class; existing rows stay readable"),
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
                                name="fk_commentable_entity_types_entity_type", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type_code", name="uq_commentable_entity_types_code"),
        schema="comments",
        comment="Which entity classes may carry comments (global).",
    )
    op.create_index(op.f("ix_comments_commentable_entity_types_uuid"), "commentable_entity_types", ["uuid"],
                    unique=True, schema="comments")

    # ── comments ─────────────────────────────────────────────────────────────
    op.create_table(
        "comments",
        sa.Column("owner_type", sa.Text(), nullable=False,
                  comment="core.entity_types.code of the owning entity, opted in via "
                          "comments.commentable_entity_types"),
        sa.Column("owner_id", sa.BigInteger(), nullable=False,
                  comment="The owner's internal id; no FK (polymorphic) and not proved to exist — the app layer "
                          "and comments.find_orphan_comments() are the checks, not a write-time trigger"),
        sa.Column("body", sa.Text(), nullable=True, comment="Comment body"),
        sa.Column("comment_type", sa.Text(), nullable=True,
                  comment="Source classification, e.g. 'system' vs a human author; free text, no CHECK"),
        sa.Column("operation_type", sa.Text(), nullable=True,
                  comment="What operation triggered a system-generated comment, if any; free text, no CHECK"),
        sa.Column("is_system_generated", sa.Boolean(),
                  sa.Computed("CASE WHEN comment_type IS NULL THEN NULL ELSE lower(comment_type) = 'system' END",
                             persisted=True),
                  nullable=True,
                  comment="STORED generated column: lower(comment_type) = 'system'; NULL when comment_type is NULL"),
        sa.Column("commented_by_external_id", sa.Text(), nullable=True,
                  comment="Opaque external (Zoho) actor id, preserved exactly — never parsed as a number"),
        sa.Column("commented_by_name", sa.Text(), nullable=True, comment="Write-time display snapshot of the author"),
        sa.Column("commented_by_user_id", sa.BigInteger(), nullable=True,
                  comment="Best-effort resolved internal users.id (no FK — same convention as AuditMixin.created_by)"),
        sa.Column("commented_at", sa.DateTime(timezone=True), nullable=False,
                  comment="Canonical business-effective instant the comment was made"),
        # ZohoIdentityMixin
        sa.Column("zoho_id", sa.String(length=50), nullable=True,
                  comment="Zoho primary key; NULL until first outbound push succeeds (most comments never push)"),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  nullable=True, comment="Local stable id; correlation reference sent to Zoho"),
        # ZohoMirrorMixin
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
        # OrgEntityMixin
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
        sa.CheckConstraint("owner_id > 0", name="ck_comments_owner_id_positive"),
        sa.ForeignKeyConstraint(["owner_type"], ["core.entity_types.code"],
                                name="fk_comments_owner_type", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "organization_id"],
                                ["org_management.organizations.tenant_id", "org_management.organizations.id"],
                                name="fk_comments_tenant_org", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="comments",
        comment="Polymorphic comment: an owning entity says something, at an instant.",
    )
    op.create_index("ix_comments_owner_commented_at", "comments", ["owner_type", "owner_id", "commented_at"],
                    unique=False, schema="comments", postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_comments_commented_by_user", "comments", ["commented_by_user_id"], unique=False,
                    schema="comments",
                    postgresql_where=sa.text("deleted_at IS NULL AND commented_by_user_id IS NOT NULL"))
    op.create_index("uq_comments_zoho_id_live", "comments", ["tenant_id", "zoho_id"], unique=True, schema="comments",
                    postgresql_where=sa.text("deleted_at IS NULL AND zoho_id IS NOT NULL"))
    op.create_index("ix_comments_tenant_org", "comments", ["tenant_id", "organization_id"], unique=False,
                    schema="comments")
    op.create_index(op.f("ix_comments_comments_deleted_at"), "comments", ["deleted_at"], unique=False,
                    schema="comments")
    op.create_index(op.f("ix_comments_comments_status"), "comments", ["status"], unique=False, schema="comments")
    op.create_index(op.f("ix_comments_comments_tenant_id"), "comments", ["tenant_id"], unique=False, schema="comments")
    op.create_index(op.f("ix_comments_comments_uuid"), "comments", ["uuid"], unique=True, schema="comments")
    op.create_index(op.f("ix_comments_comments_zoho_id"), "comments", ["zoho_id"], unique=False, schema="comments")

    # ── functions ────────────────────────────────────────────────────────────
    # No existence-proving trigger here (deliberately — see the module docstring): only
    # find_orphan_comments(), a read-only diagnostic, uses core.entity_types' schema/table
    # pointers for comments.

    op.execute("""
        CREATE FUNCTION comments.find_orphan_comments()
        RETURNS TABLE (comment_id bigint, orphan_owner_type text, orphan_owner_id bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
            r record;
        BEGIN
            FOR r IN SELECT et.code, et.target_schema, et.target_table
                       FROM core.entity_types et
                      WHERE et.deleted_at IS NULL
            LOOP
                RETURN QUERY EXECUTE format(
                    'SELECT c.id, c.owner_type, c.owner_id
                       FROM comments.comments c
                      WHERE c.owner_type = %L
                        AND c.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = c.owner_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)

    # ── the first consumer: users (app/modules/users/model.py: HasCommentsMixin) ──
    register_commentable_entity_type(
        op.get_bind(), code="user", name="User", target_schema="public", target_table="users",
        description="Notes/activity-trail entries against a user's own account.",
    )


def downgrade() -> None:
    op.execute("DELETE FROM comments.commentable_entity_types "
              "WHERE entity_type_code = 'user' AND created_by_name = 'system:migration'")
    op.execute("DELETE FROM core.entity_types "
              "WHERE code = 'user' AND created_by_name = 'system:migration'")

    op.execute("DROP FUNCTION IF EXISTS comments.find_orphan_comments()")

    op.drop_table("comments", schema="comments")
    op.drop_table("commentable_entity_types", schema="comments")
    op.execute("DROP SCHEMA IF EXISTS comments")
