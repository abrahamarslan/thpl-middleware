"""Repair the polymorphic orphan finders that could never run

``core.find_orphan_entity_aliases()`` and ``core.find_orphan_categorizables()`` are
the scheduled safety nets for a hard-deleted polymorphic target. Both declare
``RETURNS TABLE (…, <type> text, …)`` but return the ``varchar(64)`` type column
straight from their table, and ``RETURN QUERY EXECUTE`` checks the structure on
every call — so they failed with::

    structure of query does not match function result type
    Returned type character varying(64) does not match expected type text

no matter what the tables held. Nothing called them, so nothing noticed
(``extfields.find_orphan_field_values()`` casts and works). The fix is one ``::text``.

``CREATE OR REPLACE`` keeps every dependent object. There is nothing to restore on
downgrade — the previous definitions were the bug.

Revision ID: cbdb4590446e
Revises: 84daf73430b6
Create Date: 2026-09-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cbdb4590446e"
down_revision: str | None = "84daf73430b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION core.find_orphan_entity_aliases()
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
                    'SELECT a.id, a.entity_type::text, a.entity_id
                       FROM core.entity_aliases a
                      WHERE a.entity_type = %L
                        AND a.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = a.entity_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION core.find_orphan_categorizables()
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
                    'SELECT l.id, l.categorizable_type::text, l.categorizable_id
                       FROM core.categorizables l
                      WHERE l.categorizable_type = %L
                        AND l.deleted_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM %I.%I o WHERE o.id = l.categorizable_id)',
                    r.code, r.target_schema, r.target_table);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    # The previous definitions raised on every call; there is nothing worth restoring.
    pass
