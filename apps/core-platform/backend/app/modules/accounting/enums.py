"""Vocabularies of the ``accounting`` schema.

Every closed set is stored in a ``text`` column guarded by a CHECK built FROM the
enum (``values()``), so the constraint and the vocabulary cannot drift — the
``core`` / ``tax`` convention.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import values

#: Postgres schema holding the chart of accounts and account assignments.
ACCOUNTING_SCHEMA = "accounting"

#: The crosswalk module key of the chart of accounts (``sync.sync_records.module``) — what any
#: other module's source ids for an account resolve through.
CHART_OF_ACCOUNTS_MODULE = "chart_of_accounts"


class AccountGroup(enum.StrEnum):
    """The five major groups every account type belongs to."""

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"

    @property
    def is_debit_normal(self) -> bool:
        return self in (AccountGroup.ASSET, AccountGroup.EXPENSE)


class AccountStatus(enum.StrEnum):
    """The ONE activity signal of an account (Zoho ``is_active`` maps onto it)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class AccountUsage(enum.StrEnum):
    """The pickers: which accounts a sales / purchase / inventory form may offer."""

    SALES = "sales"
    PURCHASE = "purchase"
    INVENTORY = "inventory"


__all__ = ["ACCOUNTING_SCHEMA", "CHART_OF_ACCOUNTS_MODULE", "AccountGroup", "AccountStatus", "AccountUsage", "values"]
