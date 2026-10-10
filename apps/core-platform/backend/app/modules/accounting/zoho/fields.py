"""Zoho Books chart of accounts → ``accounting.accounts`` field rules (docs/zoho-docs-md/chart-of-accounts.md).

Documented attributes are mapped by their documented names. Keys seen only in undocumented
responses (``is_user_created``, ``placeholder``) are applied when present and skipped when
absent — a key the source did not send is never decoded to NULL.

Not in the field map, deliberately:

  * ``account_id`` — the crosswalk's ``external_id`` (+ the engine-maintained ``zoho_id`` echo);
  * ``parent_account_id`` — resolved through the crosswalk in ``hooks.after_account_upsert``
    (a row of the SAME module, usually in the same page — the categories reasoning);
  * ``currency_id`` — a ``ReferenceRule`` on the contract (module ``currencies``, DEFER);
  * ``created_time`` / ``last_modified_time`` — the crosswalk's ``source_modified_at``;
  * ``current_balance``, ``closing_balance``, ``is_involved_in_transaction``, ``depth``,
    ``child_count``, ``is_child_present``, ``parent_account_name``, ``has_attachment``,
    ``documents`` — volatile or derived; excluded from the no-op hash (``spec.py``), kept in
    the raw document only;
  * ``include_in_vat_return`` (UK only), ``custom_fields`` — the raw document / crosswalk.
"""

from app.modules.accounting.zoho import codecs as _codecs  # noqa: F401 — registers "account_status"
from app.modules.sync.translation import Direction, FieldSpec as F

IN, BOTH = Direction.IN, Direction.BOTH

FIELDS: list[F] = [
    F(external="account_name", local="account_name", codec="str", direction=BOTH, required_on_create=True),
    F(external="account_code", local="account_code", codec="str", direction=BOTH),     # "" → NULL
    F(external="account_type", local="account_type", codec="str", direction=BOTH, required_on_create=True),
    F(external="description", local="description", codec="str", direction=BOTH),
    F(external="is_active", local="status", codec="account_status", direction=IN),
    F(external="is_system_account", local="is_system_account", codec="bool", direction=IN),
    F(external="is_user_created", local="is_user_created", codec="bool", direction=IN),
    F(external="can_show_in_ze", local="is_expense_claim_enabled", codec="bool", direction=BOTH),
    F(external="show_on_dashboard", local="show_on_dashboard", codec="bool", direction=BOTH),
    F(external="placeholder", local="placeholder", codec="str", direction=IN),
    # In every LIVE list row (not in the documented example) — verified 2026-10-08.
    F(external="is_register_supported_account", local="is_register_supported", codec="bool", direction=IN),
    F(external="is_standalone_account", local="is_standalone", codec="bool", direction=IN),
]

#: Payload keys that change without the account changing — never part of the no-op hash.
VOLATILE_KEYS: list[str] = [
    "*_formatted", "page_context", "instrumentation",
    "current_balance", "closing_balance", "balance", "bcy_balance",
    "is_involved_in_transaction", "child_count", "is_child_present", "depth",
    "parent_account_name", "has_attachment", "documents",
    # detail-only: the side of the CURRENT balance (verified live: every zero-balance account says false), and
    # the account's recent transactions — both move without the account changing.
    "isdebit", "transactions",
]

__all__ = ["FIELDS", "VOLATILE_KEYS"]
