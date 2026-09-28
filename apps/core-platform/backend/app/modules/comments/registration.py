"""Making an entity class commentable — the ONE call a module makes to opt in.

    register_commentable_entity_type(conn, code="tax_component", name="Tax Component",
                                     target_schema="tax", target_table="tax_components")

does two idempotent things, in the migration (or seeder) of the module that owns the
entity (mirrors ``taxes/registration.py::register_taxable_entity_type`` exactly — same
two-step shape, same ``core.entity_types`` registry underneath):

  1. registers the class in ``core.entity_types`` (the platform's polymorphic registry:
     ``code`` -> ``target_schema.target_table``), unless it is already there — that row is
     what lets the database prove an ``owner_id`` exists;
  2. opts it in to comments (``comments.commentable_entity_types``).

Then the model adds ``HasCommentsMixin`` (``comments/mixins.py``). Nothing in the
``comments`` schema changes — that is the point.

Existing rows are NEVER overwritten (``ON CONFLICT DO NOTHING``): an operator who
deactivated a class keeps that across a re-run. Uses lightweight Core tables rather than
the ORM models so a migration that calls this keeps working after the models have grown
new columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

_SYSTEM = "system:migration"

_ENTITY_TYPES = sa.table(
    "entity_types",
    sa.column("code", sa.String), sa.column("name", sa.Text),
    sa.column("target_schema", sa.String), sa.column("target_table", sa.String),
    sa.column("created_by_name", sa.String),
    schema="core",
)

_COMMENTABLE = sa.table(
    "commentable_entity_types",
    sa.column("entity_type_code", sa.String), sa.column("is_active", sa.Boolean),
    sa.column("description", sa.Text), sa.column("created_by_name", sa.String),
    schema="comments",
)


def register_commentable_entity_type(
    conn: Connection, *, code: str, name: str, target_schema: str, target_table: str,
    description: str | None = None,
) -> None:
    """Register ``code`` as an entity class and opt it in to comments."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    conn.execute(
        pg_insert(_ENTITY_TYPES)
        .values(code=code, name=name, target_schema=target_schema, target_table=target_table,
                created_by_name=_SYSTEM)
        .on_conflict_do_nothing(index_elements=["code"])
    )
    conn.execute(
        pg_insert(_COMMENTABLE)
        .values(entity_type_code=code, is_active=True, description=description, created_by_name=_SYSTEM)
        .on_conflict_do_nothing(index_elements=["entity_type_code"])
    )


__all__ = ["register_commentable_entity_type"]
