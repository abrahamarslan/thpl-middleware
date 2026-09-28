"""Closed vocabularies for the custom-fields engine (schema ``extfields``).

Only the genuinely closed sets live here. The owner-type vocabulary is NOT a
Python enum: it is carried by the shared ``core.entity_types`` registry, which a
deployment grows with a row, not a migration. ``data_types.code`` is likewise an
open, Zoho-sourced vocabulary carried as rows in ``extfields.data_types`` (the
AP8 pattern) — so a new Zoho field type is a seed row, never DDL.

The sets modelled here are the ones that name physical columns or drive policy,
so the database can CHECK them:

* ``StorageColumn`` — the five typed columns on ``extfields.field_values``.
* ``PiiType`` — the DPDP classification on ``extfields.field_definitions``.
"""

from __future__ import annotations

import enum

#: Postgres schema holding the extensible custom-field engine.
EXTFIELDS_SCHEMA = "extfields"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — build a CHECK constraint from the enum so they never drift."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


class StorageColumn(enum.StrEnum):
    """The typed columns on ``extfields.field_values`` (``data_types.storage_column``)."""

    VALUE_TEXT = "value_text"
    VALUE_NUMERIC = "value_numeric"
    VALUE_DATE = "value_date"
    VALUE_BOOLEAN = "value_boolean"
    VALUE_JSON = "value_json"


class PiiType(enum.StrEnum):
    """DPDP classification of a field definition (``field_definitions.pii_type``).

    Drives erasure for every ``field_values`` row under the definition. NULL
    means *unclassified*, not non-PII — treat it as a review item before any
    erasure run.
    """

    NON_PII = "non_pii"
    PII = "pii"
    SENSITIVE_PII = "sensitive_pii"


__all__ = [
    "EXTFIELDS_SCHEMA",
    "PiiType",
    "StorageColumn",
    "values",
]