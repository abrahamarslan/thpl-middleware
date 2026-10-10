"""Pricing: rename "pricebooks" to "price lists" — tables, columns, constraints, indexes, sequences and every stored module key.

Zoho's API calls the resource a *pricebook*; the platform calls it a **price list** (owner decision,
2026-10-08). Zoho's own spelling now survives only where we read Zoho's payload (the adapter's field
map: ``/pricebooks``, ``pricebook_id``, ``pricebook_items`` …).

Tables (schema ``pricing`` unchanged):

    pricebooks               → price_lists
    pricebook_items          → price_list_items
    pricebook_item_brackets  → price_list_item_brackets

Columns:

    price_lists               pricebook_type → price_list_type,  pricebook_rate → rate
    price_list_items          pricebook_id → price_list_id,  pricebook_rate → rate,  pricebook_discount → discount
    price_list_item_brackets  pricebook_item_id → price_list_item_id,  pricebook_rate → rate,
                              pricebook_discount → discount

Every constraint (CHECK, FK, PK, UNIQUE and PG18's named NOT NULL), index and owned sequence whose
name contains ``pricebook`` is renamed by substituting ``price_list`` — read from the catalog, so none
is missed and a fresh database (previous migration + this one) carries exactly the dev database's
names. One name is chosen rather than substituted: ``uq_pricebook_items_book_item`` →
``uq_price_list_items_list_item``. CHECK expressions and partial-index predicates follow the column
renames on their own (Postgres stores them parsed).

Stored references to the crosswalk module key ``pricebooks`` → ``price_lists`` (and the entity table
``pricing.pricebooks`` → ``pricing.price_lists``), so identity, history and operations continue
unbroken — the next sync finds every row and writes nothing:

    sync.sync_records (module, entity_table) · sync.sync_payloads (module, entity_table)
    sync.pending_references (module, waiting_table) · zoho_sync_runs · zoho_sync_events
    zoho_sync_cursors · zoho_sync_stats · zoho_queue_logs · zoho_sync_state
    zoho_retention_policies (module, table_name) · control-plane overrides
    (setting_definitions ``zoho.module.pricebooks.<knob>``)

plus the projection's soft-delete marker ``zoho:removed_from_pricebook`` →
``zoho:removed_from_price_list``. ``setting_audit_logs`` keeps its history verbatim (an audit trail is
never rewritten).

Downgrade reverses all of it.

Revision ID: 7c3e91a05d24
Revises: 02b470ed2792
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c3e91a05d24"
down_revision: str | None = "02b470ed2792"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [("pricebooks", "price_lists"), ("pricebook_items", "price_list_items"),
           ("pricebook_item_brackets", "price_list_item_brackets")]
#: (new table name, old column, new column)
_COLUMNS = [
    ("price_lists", "pricebook_type", "price_list_type"),
    ("price_lists", "pricebook_rate", "rate"),
    ("price_list_items", "pricebook_id", "price_list_id"),
    ("price_list_items", "pricebook_rate", "rate"),
    ("price_list_items", "pricebook_discount", "discount"),
    ("price_list_item_brackets", "pricebook_item_id", "price_list_item_id"),
    ("price_list_item_brackets", "pricebook_rate", "rate"),
    ("price_list_item_brackets", "pricebook_discount", "discount"),
]
#: Names chosen rather than substituted (old → new).
_CHOSEN = {"uq_pricebook_items_book_item": "uq_price_list_items_list_item"}

#: (table, column or None for the table, upgraded comment, downgraded comment) — columns named post-upgrade.
_COMMENTS = [
    ("price_lists", None,
     "Price lists of one organization (Zoho: pricebooks); Zoho crosswalk module price_lists.",
     "Price lists (Zoho pricebooks) of one organization; Zoho crosswalk."),
    ("price_lists", "price_list_type", "per_item | fixed_percentage (Zoho pricebook_type)",
     "per_item | fixed_percentage"),
    ("price_lists", "pricing_scheme",
     'unit | volume (per_item lists); NULL for fixed_percentage (Zoho sends "")',
     'unit | volume (per_item books); NULL for fixed_percentage (Zoho sends "")'),
    ("price_lists", "rate", "List-level rate as Zoho sends it (Zoho pricebook_rate; observed = percentage)",
     "Book-level rate as Zoho sends it (observed = percentage); NOT a bracket's rate"),
    ("price_lists", "is_default", "Zoho's default price list flag (DETAIL document only; NULL until the detail lands)",
     "Zoho's default pricebook flag (DETAIL document only; NULL until the detail lands)"),
    ("price_list_items", None, "Items of a per_item price list (unit rate, or parent of brackets).",
     "Items of a per_item pricebook (unit rate, or parent of brackets)."),
    ("price_list_items", "item_name", "Item name as embedded in the price list (snapshot)",
     "Item name as embedded in the pricebook (snapshot)"),
    ("price_list_items", "rate", "Unit-scheme price of the item (Zoho pricebook_rate)", "Unit-scheme price of the item"),
    ("price_list_items", "discount", 'Zoho pricebook_discount verbatim (e.g. "5%"); NULL when Zoho sends ""',
     'Zoho\'s discount string verbatim (e.g. "5%"); NULL when Zoho sends ""'),
    ("price_list_item_brackets", None, "Quantity brackets of a volume price list's item.",
     "Quantity brackets of a volume pricebook's item."),
    ("price_list_item_brackets", "rate", "Unit price within this bracket (Zoho pricebook_rate)",
     "Unit price within this bracket"),
    ("price_list_item_brackets", "discount", "Zoho pricebook_discount verbatim", "Zoho's discount string verbatim"),
]

#: (table, column) pairs holding a module key or an entity table name.
_MODULE_COLUMNS = [
    ("sync.sync_records", "module"), ("sync.sync_payloads", "module"), ("sync.pending_references", "module"),
    ("zoho_sync_runs", "module"), ("zoho_sync_events", "module"), ("zoho_sync_cursors", "module"),
    ("zoho_sync_stats", "module_name"), ("zoho_queue_logs", "module_name"), ("zoho_sync_state", "entity"),
    ("zoho_retention_policies", "module"),
]
_TABLE_COLUMNS = [
    ("sync.sync_records", "entity_table"), ("sync.sync_payloads", "entity_table"),
    ("sync.pending_references", "waiting_table"), ("zoho_retention_policies", "table_name"),
]


def _q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _rename_objects(old: str, new: str, chosen: dict[str, str]) -> None:
    """Rename every constraint, then every remaining index, then every sequence in ``pricing``."""
    bind = op.get_bind()

    def target(name: str) -> str:
        return chosen.get(name, name.replace(old, new))

    for table, name in bind.execute(sa.text(
        "SELECT c.relname, k.conname FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid "
        "WHERE k.connamespace = 'pricing'::regnamespace AND k.conname LIKE :pat ORDER BY 1, 2"),
        {"pat": f"%{old}%"}).all():
        op.execute(f'ALTER TABLE pricing."{table}" RENAME CONSTRAINT "{name}" TO "{target(name)}"')
    for kind, statement in (("i", "INDEX"), ("S", "SEQUENCE")):
        for (name,) in bind.execute(sa.text(
            "SELECT relname FROM pg_class WHERE relnamespace = 'pricing'::regnamespace "
            "AND relkind::text = :kind AND relname LIKE :pat ORDER BY 1"), {"kind": kind, "pat": f"%{old}%"}).all():
            op.execute(f'ALTER {statement} pricing."{name}" RENAME TO "{target(name)}"')


def _rewrite_keys(old_module: str, new_module: str, old_table: str, new_table: str,
                  old_reason: str, new_reason: str, tables: tuple[str, str]) -> None:
    for table, column in _MODULE_COLUMNS:
        op.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old")
                   .bindparams(old=old_module, new=new_module))
    for table, column in _TABLE_COLUMNS:
        op.execute(sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old")
                   .bindparams(old=old_table, new=new_table))
    op.execute(sa.text("UPDATE setting_definitions SET key = :new || substr(key, length(:old) + 1) "
                       "WHERE key LIKE :old || '%'")
               .bindparams(old=f"zoho.module.{old_module}.", new=f"zoho.module.{new_module}."))
    for table in tables:
        op.execute(sa.text(f"UPDATE pricing.{table} SET deleted_reason = :new WHERE deleted_reason = :old")
                   .bindparams(old=old_reason, new=new_reason))


def _comments(index: int) -> None:
    for table, column, *texts in _COMMENTS:
        target = f"pricing.{table}" if column is None else f"pricing.{table}.{column}"
        op.execute(f"COMMENT ON {'TABLE' if column is None else 'COLUMN'} {target} IS {_q(texts[index])}")


def upgrade() -> None:
    for old, new in _TABLES:
        op.rename_table(old, new, schema="pricing")
    for table, old, new in _COLUMNS:
        op.alter_column(table, old, new_column_name=new, schema="pricing")
    _rename_objects("pricebook", "price_list", _CHOSEN)
    _comments(0)
    _rewrite_keys("pricebooks", "price_lists", "pricing.pricebooks", "pricing.price_lists",
                  "zoho:removed_from_pricebook", "zoho:removed_from_price_list",
                  ("price_list_items", "price_list_item_brackets"))


def downgrade() -> None:
    _rewrite_keys("price_lists", "pricebooks", "pricing.price_lists", "pricing.pricebooks",
                  "zoho:removed_from_price_list", "zoho:removed_from_pricebook",
                  ("price_list_items", "price_list_item_brackets"))
    _comments(1)
    _rename_objects("price_list", "pricebook", {new: old for old, new in _CHOSEN.items()})
    for table, old, new in reversed(_COLUMNS):
        op.alter_column(table, new, new_column_name=old, schema="pricing")
    for old, new in reversed(_TABLES):
        op.rename_table(new, old, schema="pricing")
