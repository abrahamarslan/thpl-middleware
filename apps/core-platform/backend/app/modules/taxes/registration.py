"""Making an entity class taxable — the ONE call a module makes to opt in.

    register_taxable_entity_type(conn, code="item", name="Item",
                                 target_schema="catalog", target_table="items",
                                 allows_exemption=True)

does two idempotent things, in the migration (or seeder) of the module that owns
the entity:

  1. registers the class in ``core.entity_types`` (the platform's polymorphic
     registry: ``code`` → ``target_schema.target_table``), unless it is already
     there — that row is what lets the database prove an ``owner_id`` exists;
  2. opts it in to tax assignments with its rule (``tax.taxable_entity_types``).

Then the model adds ``HasTaxesMixin`` (``taxes/mixins.py``). Nothing in the ``tax``
schema changes — that is the point.

Existing rows are NEVER overwritten (``ON CONFLICT DO NOTHING``): an operator who
tightened a rule keeps it across a re-run. Uses lightweight Core tables rather
than the ORM models so a migration that calls this keeps working after the
models have grown new columns.

The rule, per class:

    allows_multiple    False (default): at most ONE tax per (owner, inter/intra,
                       sales/purchase) context — the shape of Zoho's category /
                       item / contact taxes. True: several taxes apply together
                       (an invoice line's IGST + cess).
    allows_exemption   True lets the class carry a ``tax_exemption`` too (items,
                       contacts, lines). Categories do not.
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

_TAXABLE = sa.table(
    "taxable_entity_types",
    sa.column("entity_type_code", sa.String), sa.column("allows_multiple", sa.Boolean),
    sa.column("allows_exemption", sa.Boolean), sa.column("description", sa.Text),
    sa.column("created_by_name", sa.String),
    schema="tax",
)


def register_taxable_entity_type(
    conn: Connection, *, code: str, name: str, target_schema: str, target_table: str,
    allows_multiple: bool = False, allows_exemption: bool = False, description: str | None = None,
) -> None:
    """Register ``code`` as an entity class and opt it in to tax assignments."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    conn.execute(
        pg_insert(_ENTITY_TYPES)
        .values(code=code, name=name, target_schema=target_schema, target_table=target_table,
                created_by_name=_SYSTEM)
        .on_conflict_do_nothing(index_elements=["code"])
    )
    conn.execute(
        pg_insert(_TAXABLE)
        .values(entity_type_code=code, allows_multiple=allows_multiple, allows_exemption=allows_exemption,
                description=description, created_by_name=_SYSTEM)
        .on_conflict_do_nothing(index_elements=["entity_type_code"])
    )


__all__ = ["register_taxable_entity_type"]
