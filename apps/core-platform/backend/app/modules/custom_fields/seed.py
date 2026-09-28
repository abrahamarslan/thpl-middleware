"""The ``extfields.data_types`` lookup — Zoho's custom-field vocabulary.

``code`` is the open, Zoho-sourced vocabulary; ``storage_column`` is the closed
set of typed columns on ``field_values`` it maps to. This table is the AP8
pattern applied precisely: the vocabulary that can grow is DATA (a seed row, no
migration), while the physical column set is a CHECK on ``storage_column``.

``seed_data_types`` inserts only rows that are missing and NEVER overwrites an
existing one, so an operator's correction survives a re-seed. Called from the
migration that creates the table and from ``scripts/seed.py``.

Uses a lightweight Core table (not the ORM model) so the seeder keeps working
from an old migration after the model has grown new columns.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.modules.custom_fields.enums import EXTFIELDS_SCHEMA, StorageColumn

_S = StorageColumn

#: Zoho custom-field data_type code -> (label, storage column). Open vocabulary.
SEED_DATA_TYPES: tuple[tuple[str, str, StorageColumn], ...] = (
    # numeric
    ("amount", "Amount", _S.VALUE_NUMERIC),
    ("decimal", "Decimal", _S.VALUE_NUMERIC),
    ("percent", "Percent", _S.VALUE_NUMERIC),
    ("number", "Number", _S.VALUE_NUMERIC),
    # text
    ("autonumber", "Auto Number", _S.VALUE_TEXT),
    ("text", "Text", _S.VALUE_TEXT),
    ("textarea", "Text Area", _S.VALUE_TEXT),
    ("email", "Email", _S.VALUE_TEXT),
    ("phone", "Phone", _S.VALUE_TEXT),
    ("url", "URL", _S.VALUE_TEXT),
    ("attachment", "Attachment", _S.VALUE_TEXT),
    ("dropdown", "Dropdown", _S.VALUE_TEXT),
    # date / time
    ("date", "Date", _S.VALUE_DATE),
    ("datetime", "Date & Time", _S.VALUE_DATE),
    # boolean
    ("checkbox", "Checkbox", _S.VALUE_BOOLEAN),
    # structured
    ("multiselect", "Multi-select", _S.VALUE_JSON),
)


def catalog() -> list[dict[str, Any]]:
    """The seed rows as plain dicts (formulas applied)."""
    return [
        {"code": code, "label": label, "storage_column": storage.value}
        for code, label, storage in SEED_DATA_TYPES
    ]


#: The columns this seeder writes — frozen on purpose: it must keep working on a
#: database that has not yet received later columns.
_TABLE = sa.table(
    "data_types",
    sa.column("code", sa.String),
    sa.column("label", sa.String),
    sa.column("storage_column", sa.String),
    schema=EXTFIELDS_SCHEMA,
)


def seed_data_types(conn: Connection) -> int:
    """Insert the missing lookup rows; return how many were added.

    ``ON CONFLICT DO NOTHING`` with no target: the live-code uniqueness is a
    PARTIAL index, which cannot be named as an arbiter on every Postgres, so the
    target-less form (catch any unique violation) is the portable idempotent
    seed. Existing rows are never overwritten.
    """
    stmt = pg_insert(_TABLE).values(catalog()).on_conflict_do_nothing()
    return conn.execute(stmt).rowcount or 0


__all__ = ["SEED_DATA_TYPES", "catalog", "seed_data_types"]