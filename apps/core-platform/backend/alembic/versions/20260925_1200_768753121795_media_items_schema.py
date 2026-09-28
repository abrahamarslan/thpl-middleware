"""Media — schema ``media``: ``media.items`` replaces the orphaned ``public.media``

One row per stored file (original + generated conversions), for public
(avatars) and private (documents) collections, on local disk or Garage:

  * ``disk`` and ``visibility`` are recorded PER ROW, so changing
    MEDIA_STORAGE_DRIVER for new uploads never strands an issued URL and a
    private row can never be served by the public router;
  * ``uuid`` is the public media id and the prefix of every storage key
    (``{uuid}/{variant}.{ext}``); ``id`` stays internal;
  * ``status`` is the CONVERSION lifecycle (it overrides StatusMixin's ``active``).

The v1 ``public.media`` table (int PK, flat file names, ``model_id`` as text) had
no consumer: no model inherited HasMediaMixin and nothing imported its service.
Its bytes also sit under a different key layout than the new
``<base>/<visibility>/<uuid>/<variant>`` one, so rows cannot be carried across by
SQL alone. The upgrade therefore REFUSES to drop it while it still holds live
rows, instead of silently losing them. Downgrade recreates the empty v1 table —
lossy: rows written to ``media.items`` are dropped with it.

Revision ID: 768753121795
Revises: c7a1e9b2d4f8
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "768753121795"
down_revision: str | None = "c7a1e9b2d4f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    live = conn.execute(sa.text("SELECT count(*) FROM public.media WHERE deleted_at IS NULL")).scalar()
    if live:
        raise RuntimeError(
            f"public.media still holds {live} live row(s). The new media module stores files under a "
            "different key layout, so they cannot be migrated by SQL. Export or delete them "
            "(UPDATE public.media SET deleted_at = now() once their bytes are dealt with), then re-run."
        )

    op.execute("CREATE SCHEMA IF NOT EXISTS media")
    op.create_table(
        "items",
        sa.Column("model_type", sa.String(length=50), nullable=False, comment="Owning entity class, e.g. 'user' (no FK)"),
        sa.Column("model_id", sa.BigInteger(), nullable=False, comment="Owning entity id (no FK)"),
        sa.Column("collection", sa.String(length=50), nullable=False, comment="Named group per owner: 'avatar', 'documents', …"),
        sa.Column("disk", sa.String(length=20), nullable=False, comment="Where THIS file lives: local | garage (never inferred from settings)"),
        sa.Column("visibility", sa.String(length=20), server_default=sa.text("'private'"), nullable=False, comment="public | private — decides the bucket and whether /public/m may serve it"),
        sa.Column("file_name", sa.Text(), nullable=False, comment="Storage key of the ORIGINAL"),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("conversions", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment="{variant: {status, file_name, w, h, size}} — one key per variant, written by Celery"),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False, comment="Conversion lifecycle: pending | processing | done | partial_failure"),
        sa.Column("uuid", sa.UUID(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="Tenant isolation key"),
        sa.Column("organization_id", sa.BigInteger(), nullable=False, comment="Organization within the tenant (required)"),
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.String(length=255), nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="users.id of the last updater"),
        sa.Column("updated_by_name", sa.String(length=255), nullable=True, comment="Last updater display name at the time"),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False, comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("app_version", sa.String(length=32), nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.Text(), nullable=True, comment="Why it was deleted"),
        sa.CheckConstraint("disk IN ('local','garage')", name="chk_media_disk"),
        sa.CheckConstraint("status IN ('pending','processing','done','partial_failure')", name="chk_media_status"),
        sa.CheckConstraint("visibility IN ('public','private')", name="chk_media_visibility"),
        sa.CheckConstraint("size_bytes >= 0", name="chk_media_size"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            ["org_management.organizations.tenant_id", "org_management.organizations.id"],
            name="fk_items_tenant_org", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="media",
        comment="Stored files (originals) and their generated conversions.",
    )
    op.create_index("ix_items_tenant_org", "items", ["tenant_id", "organization_id"], unique=False, schema="media")
    op.create_index(op.f("ix_media_items_deleted_at"), "items", ["deleted_at"], unique=False, schema="media")
    op.create_index(
        "ix_media_items_owner", "items", ["tenant_id", "model_type", "model_id", "collection"],
        unique=False, schema="media", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(op.f("ix_media_items_tenant_id"), "items", ["tenant_id"], unique=False, schema="media")
    op.create_index(op.f("ix_media_items_uuid"), "items", ["uuid"], unique=True, schema="media")

    # Retire the v1 table (empty of live rows — guarded above).
    op.drop_table("media")


def downgrade() -> None:
    op.create_table(
        "media",
        sa.Column("uuid", sa.UUID(), autoincrement=False, nullable=False, comment="Public identifier"),
        sa.Column("model_type", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("model_id", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("collection_name", sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column("file_name", sa.VARCHAR(length=255), autoincrement=False, nullable=False, comment="Stored (disk) file name"),
        sa.Column("original_name", sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment="Client-supplied name"),
        sa.Column("mime_type", sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        sa.Column("disk", sa.VARCHAR(length=20), autoincrement=False, nullable=True, comment="Storage driver: local | s3"),
        sa.Column("size", sa.INTEGER(), autoincrement=False, nullable=True, comment="Bytes"),
        sa.Column("conversions", postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column("custom_properties", postgresql.JSONB(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column("order_column", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), autoincrement=False, nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), autoincrement=False, nullable=False),
        sa.Column("deleted_at", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
        sa.Column("tenant_id", sa.BIGINT(), autoincrement=False, nullable=False, comment="Owning tenant (isolation key)"),
        sa.Column("organization_id", sa.BIGINT(), autoincrement=False, nullable=True, comment="Owning organization within the tenant; NULL = tenant-wide"),
        sa.Column("app_version", sa.VARCHAR(length=32), autoincrement=False, nullable=True, comment="App version that last wrote the row"),
        sa.Column("app_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), autoincrement=False, nullable=False),
        sa.Column("created_by", sa.BIGINT(), autoincrement=False, nullable=True, comment="users.id of the creator (NULL = system)"),
        sa.Column("created_by_name", sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment="Creator display name at the time"),
        sa.Column("updated_by", sa.BIGINT(), autoincrement=False, nullable=True, comment="users.id of the last updater"),
        sa.Column("status", sa.VARCHAR(length=20), server_default=sa.text("'active'::character varying"), autoincrement=False, nullable=False),
        sa.Column("is_verified", sa.BOOLEAN(), server_default=sa.text("false"), autoincrement=False, nullable=False),
        sa.Column("row_version", sa.INTEGER(), server_default=sa.text("1"), autoincrement=False, nullable=False, comment="Optimistic-lock counter (incremented on every update)"),
        sa.Column("deleted_by", sa.BIGINT(), autoincrement=False, nullable=True, comment="users.id who deleted it"),
        sa.Column("deleted_reason", sa.TEXT(), autoincrement=False, nullable=True, comment="Why it was deleted"),
        sa.Column("updated_by_name", sa.VARCHAR(length=255), autoincrement=False, nullable=True, comment="Last updater display name at the time"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "organization_id"],
            ["org_management.organizations.tenant_id", "org_management.organizations.id"],
            name=op.f("fk_media_tenant_org"), ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["org_management.tenants.id"], name=op.f("media_tenant_id_fkey"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("media_pkey")),
        sa.UniqueConstraint("uuid", name=op.f("media_uuid_key")),
    )
    op.create_index(op.f("ix_media_tenant_org"), "media", ["tenant_id", "organization_id"], unique=False)
    op.create_index(op.f("ix_media_tenant_id"), "media", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_media_status"), "media", ["status"], unique=False)
    op.create_index(op.f("ix_media_owner"), "media", ["model_type", "model_id", "collection_name"], unique=False)
    op.create_index(op.f("ix_media_model_type"), "media", ["model_type"], unique=False)
    op.create_index(op.f("ix_media_model_id"), "media", ["model_id"], unique=False)
    op.create_index(op.f("ix_media_deleted_at"), "media", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_media_collection_name"), "media", ["collection_name"], unique=False)

    op.drop_table("items", schema="media")
    op.execute("DROP SCHEMA IF EXISTS media")
