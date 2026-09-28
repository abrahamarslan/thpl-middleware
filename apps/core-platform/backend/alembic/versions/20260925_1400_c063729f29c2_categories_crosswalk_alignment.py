"""Categories — align core.categories with the crosswalk shape

``categories`` is a crosswalk module (``SyncContract.crosswalk=True``): identity,
the apply gate's fence/hash, the raw document and the custom fields live in
``sync.sync_records`` / ``sync.sync_payloads``. The first cut of the table still
composed the in-place mirror mixins, so it carried fourteen columns the
crosswalk path never writes (``zoho_raw`` … ``sync_version``, the push state,
``public_id``) — a live sync left every one of them NULL / 0.

This revision drops them and keeps the one Zoho column a crosswalk entity keeps:
the ``zoho_id`` echo (and its partial unique index ``uq_categories_zoho_id_live``).
Same division as ``currency.currencies`` and ``org_management.organizations``
(docs/implementation-plan/sync-crosswalk-delta-v3.md §3).

Also here:

  * ``core.set_category_is_root()`` — ``is_root`` is derived from ``parent_id``.
    Anything that writes ``parent_id`` without going through the ORM (the
    generic reconcile lane's ``UPDATE … SET parent_id``) would otherwise leave
    ``is_root = true`` beside a parent and trip ``ck_categories_root_no_parent``,
    aborting the whole drain;
  * ``meta_keywords`` becomes a JSON array (Zoho's ``seo_keyword`` is one
    comma-separated string); any string already stored is split.

Revision ID: c063729f29c2
Revises: 768753121795
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c063729f29c2"
down_revision: str | None = "768753121795"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEAD_COLUMNS = (
    "public_id", "zoho_raw", "zoho_raw_hash", "zoho_raw_synced_at", "zoho_last_modified_time",
    "synced_at", "sync_source", "sync_version", "remote_deleted_at", "custom_fields",
    "sync_state", "pending_command_id", "last_pushed_at", "last_push_error",
)


#: Column comments the model declares and the original migration never set —
#: settled here so ``alembic check`` is quiet for these four tables. (table, column) → comment.
_COMMENTS: dict[tuple[str, str], str] = {
    ("categories", "zoho_id"): "Echo of Zoho's category_id, written by the sync engine; "
                               "identity of record is sync.sync_records",
    ("categories", "category"): "Source 'category' label",
    ("categories", "code"): "Short internal code, unique per taxonomy",
    ("categories", "slug"): "URL-friendly key, unique per taxonomy",
    ("categories", "type"): "Source classification",
    ("categories", "taxonomy_slug"): "Denormalised, follows a rename",
    ("categories", "parent_id"): "NULL = root of the taxonomy",
    ("categories", "can_have_children"): "Service-set; the scope guard refuses a child under a leaf",
    ("categories", "path"): "Text breadcrumb, maintained by tree.py",
    ("categories", "status"): "active / archived",
    ("taxonomies", "status"): "draft / active / retired",
}
#: What the first cut of the migration had for these (for a faithful downgrade).
_OLD_COMMENTS: dict[tuple[str, str], str | None] = {
    key: None for key in _COMMENTS
} | {("categories", "zoho_id"): "Zoho primary key; NULL until first outbound push succeeds"}


def _set_comments(comments: dict[tuple[str, str], str | None]) -> None:
    for (table, column), comment in comments.items():
        literal = "NULL" if comment is None else "'" + comment.replace("'", "''") + "'"
        op.execute(f"COMMENT ON COLUMN core.{table}.{column} IS {literal}")


def upgrade() -> None:
    # Dropping a column drops the indexes that cover it (ix_categories_public_id,
    # ix_categories_zoho_last_modified_time, ix_categories_sync_state).
    for column in _DEAD_COLUMNS:
        op.drop_column("categories", column, schema="core")
    _set_comments(_COMMENTS)

    # Zoho's seo_keyword is "a, b, c"; the column is a JSON array of strings.
    op.execute("""
        UPDATE core.categories
           SET meta_keywords = (SELECT jsonb_agg(btrim(k))          -- NULL when nothing is left,
                                  FROM unnest(string_to_array(meta_keywords #>> '{}', ',')) AS k
                                 WHERE btrim(k) <> '')             -- like the csv_list codec
         WHERE jsonb_typeof(meta_keywords) = 'string'
    """)
    op.alter_column("categories", "meta_keywords", schema="core", existing_type=postgresql.JSONB(),
                    comment="JSON array of keyword strings (Zoho sends one comma-separated string)")

    op.execute("""
        CREATE FUNCTION core.set_category_is_root() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.is_root := (NEW.parent_id IS NULL);
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_categories_is_root
            BEFORE INSERT OR UPDATE OF parent_id ON core.categories
            FOR EACH ROW EXECUTE FUNCTION core.set_category_is_root();
    """)
    # Existing rows: bring the flag in line once (the trigger only fires on writes).
    op.execute("UPDATE core.categories SET is_root = (parent_id IS NULL) "
               "WHERE is_root IS DISTINCT FROM (parent_id IS NULL)")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_categories_is_root ON core.categories")
    op.execute("DROP FUNCTION IF EXISTS core.set_category_is_root()")

    op.alter_column("categories", "meta_keywords", schema="core", existing_type=postgresql.JSONB(),
                    comment=None)
    _set_comments(_OLD_COMMENTS)

    # ZohoIdentityMixin.public_id
    op.add_column("categories", sa.Column(
        "public_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=True,
        comment="Local stable id; correlation reference sent to Zoho"), schema="core")
    op.create_index("ix_categories_public_id", "categories", ["public_id"], unique=True, schema="core")
    # ZohoMirrorMixin
    op.add_column("categories", sa.Column("zoho_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                                          comment="Full untouched Zoho document"), schema="core")
    op.add_column("categories", sa.Column("zoho_raw_hash", sa.LargeBinary(), nullable=True,
                                          comment="sha256 of zoho_raw minus volatile keys (apply-gate no-op check)"),
                  schema="core")
    op.add_column("categories", sa.Column("zoho_raw_synced_at", sa.DateTime(timezone=True), nullable=True),
                  schema="core")
    op.add_column("categories", sa.Column("zoho_last_modified_time", sa.DateTime(timezone=True), nullable=True,
                                          comment="Zoho version of the stored data (monotonic fence)"),
                  schema="core")
    op.create_index("ix_categories_zoho_last_modified_time", "categories", ["zoho_last_modified_time"],
                    unique=False, schema="core")
    op.add_column("categories", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True), schema="core")
    op.add_column("categories", sa.Column("sync_source", sa.String(length=48), nullable=True), schema="core")
    op.add_column("categories", sa.Column("sync_version", sa.BigInteger(), server_default=sa.text("0"),
                                          nullable=False), schema="core")
    op.add_column("categories", sa.Column("remote_deleted_at", sa.DateTime(timezone=True), nullable=True),
                  schema="core")
    op.add_column("categories", sa.Column("custom_fields", postgresql.HSTORE(), nullable=True), schema="core")
    # ZohoPushableMixin
    op.add_column("categories", sa.Column("sync_state", sa.String(length=20), nullable=True), schema="core")
    op.create_index("ix_categories_sync_state", "categories", ["sync_state"], unique=False, schema="core")
    op.add_column("categories", sa.Column("pending_command_id", sa.BigInteger(), nullable=True), schema="core")
    op.add_column("categories", sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
                  schema="core")
    op.add_column("categories", sa.Column("last_push_error", sa.Text(), nullable=True), schema="core")
