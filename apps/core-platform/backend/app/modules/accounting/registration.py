"""Making an entity class carry accounts — the ONE call a module makes to opt in.

    register_account_owner_type(conn, code="item", name="Item",
                                target_schema="catalog", target_table="items",
                                purposes={"sales": True, "purchase": True, "inventory_asset": True})

does two idempotent things, in the migration (or seeder) of the module that owns the entity:

  1. registers the class in ``core.entity_types`` (code → ``target_schema.target_table``)
     unless it is already there — the row that lets the database prove an ``owner_id``;
  2. opts it in to each purpose (``accounting.account_purpose_policies``); the value is
     ``falls_back_to_organization``: when the owner carries nothing for that purpose, does
     resolution ask the organization? (True for almost everything; False for the
     organization itself — it IS the end of the chain.)

Existing rows are NEVER overwritten (``ON CONFLICT DO NOTHING``): an operator who disabled
a purpose keeps it disabled across a re-run. Lightweight Core tables, not the ORM models, so
a migration calling this keeps working after the models grow new columns (the
``taxes.registration`` rule).
"""

from __future__ import annotations

from collections.abc import Mapping

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

_POLICIES = sa.table(
    "account_purpose_policies",
    sa.column("entity_type_code", sa.String), sa.column("purpose_code", sa.String),
    sa.column("falls_back_to_organization", sa.Boolean), sa.column("description", sa.Text),
    sa.column("created_by_name", sa.String),
    schema="accounting",
)


def register_account_owner_type(
    conn: Connection, *, code: str, name: str, target_schema: str, target_table: str,
    purposes: Mapping[str, bool], description: str | None = None,
) -> None:
    """Register ``code`` as an entity class and opt it in to ``purposes``."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    conn.execute(
        pg_insert(_ENTITY_TYPES)
        .values(code=code, name=name, target_schema=target_schema, target_table=target_table,
                created_by_name=_SYSTEM)
        .on_conflict_do_nothing(index_elements=["code"])
    )
    for purpose, falls_back in purposes.items():
        conn.execute(
            pg_insert(_POLICIES)
            .values(entity_type_code=code, purpose_code=purpose, falls_back_to_organization=falls_back,
                    description=description, created_by_name=_SYSTEM)
            .on_conflict_do_nothing(index_elements=["entity_type_code", "purpose_code"])
        )


__all__ = ["register_account_owner_type"]
