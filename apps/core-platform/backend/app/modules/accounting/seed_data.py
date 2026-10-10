"""Seed data of the ``accounting`` schema — data, loaded by the migration.

ACCOUNT TYPES — all 46, the union of two sources (docs/implementation-plan/accounts-module.md §2.4):

  * Zoho Books API docs, ``account_type`` allowed values (38 codes);
  * THPL's own account-types response (26 types, WITH Zoho's numeric ids and
    per-type rules) — vendored as ``docs/zoho-docs-md/samples/accounts/account-types.json``
    and asserted field by field by ``tests/test_accounting.py``.

A type the tenant never reported carries ``zoho_id=None`` and ``None`` for the three
Zoho rules (``is_sub_account_allowed`` / ``can_show_opening_balance`` /
``can_enable_in_ze``): unknown is stored as unknown, never guessed. The sync fills the
id the first time Zoho reports one (``zoho/hooks.py``).

Normal side: asset and expense are debit-normal, the rest credit-normal.

Picker eligibility (``AccountUsage``) — the item form's dropdowns, derived from the type:
  sales      the income group
  purchase   the expense group + the capitalisable asset types
  inventory  ``stock``

PURPOSES — why an entity points at an account (§5.4). ``groups`` restricts the account's
group, ``types`` (optional) its exact type. Accountant-approved (2026-10-08).
"""

from __future__ import annotations

from typing import Any

# (code, zoho_id, name, group, sub_allowed, opening_balance, zoho_expense, asset_type, documented)
_TYPES: tuple[tuple[Any, ...], ...] = (
    # ── asset ───────────────────────────────────────────────────────────────
    ("other_asset", "1", "Other Asset", "asset", True, True, True, None, True),
    ("other_current_asset", "2", "Other Current Asset", "asset", True, True, True, None, True),
    ("cash", "3", "Cash", "asset", True, True, True, None, True),
    ("bank", "4", "Bank", "asset", False, False, True, None, True),
    ("fixed_asset", "6", "Fixed Asset", "asset", True, True, True, "fixed_asset", True),
    ("accounts_receivable", "5", "Accounts Receivable", "asset", True, False, False, None, True),
    ("stock", "19", "Stock", "asset", True, False, False, None, False),
    ("payment_clearing", "20", "Payment Clearing Account", "asset", False, True, False, None, False),
    ("intangible_asset", "25", "Intangible Asset", "asset", True, True, True, None, True),
    ("long_term_asset", "26", "Non Current Asset", "asset", True, True, False, None, False),
    ("deferred_tax_asset", "27", "Deferred Tax Asset", "asset", False, True, False, None, False),
    ("capital_work_in_progress", "111", "Capital Work In Progress", "asset", False, True, False, "cwip", False),
    ("intangible_assets_under_development", "112", "Intangible Assets Under Development", "asset",
     False, True, False, "iaud", False),
    ("right_to_use_asset", None, "Right To Use Asset", "asset", None, None, None, None, True),
    ("financial_asset", None, "Financial Asset", "asset", None, None, None, None, True),
    ("contingent_asset", None, "Contingent Asset", "asset", None, None, None, None, True),
    ("contract_asset", None, "Contract Asset", "asset", None, None, None, None, True),
    # ── liability ───────────────────────────────────────────────────────────
    ("other_current_liability", "8", "Other Current Liability", "liability", True, True, True, None, True),
    ("credit_card", "9", "Credit Card", "liability", False, False, True, None, True),
    ("long_term_liability", "11", "Non Current Liability", "liability", True, True, True, None, True),
    ("other_liability", "12", "Other Liability", "liability", True, True, True, None, True),
    ("accounts_payable", "10", "Accounts Payable", "liability", True, False, False, None, True),
    ("overseas_tax_payable", "22", "Overseas Tax Payable", "liability", False, True, False, None, False),
    ("deferred_tax_liability", "28", "Deferred Tax Liability", "liability", False, True, False, None, False),
    ("contract_liability", None, "Contract Liability", "liability", None, None, None, None, True),
    ("refund_liability", None, "Refund Liability", "liability", None, None, None, None, True),
    ("loans_and_borrowing", None, "Loans And Borrowing", "liability", None, None, None, None, True),
    ("lease_liability", None, "Lease Liability", "liability", None, None, None, None, True),
    ("employee_benefit_liability", None, "Employee Benefit Liability", "liability", None, None, None, None, True),
    ("contingent_liability", None, "Contingent Liability", "liability", None, None, None, None, True),
    ("financial_liability", None, "Financial Liability", "liability", None, None, None, None, True),
    # ── equity ──────────────────────────────────────────────────────────────
    ("equity", "13", "Equity", "equity", True, True, False, None, True),
    # ── income ──────────────────────────────────────────────────────────────
    ("income", "14", "Income", "income", True, True, False, None, True),
    ("other_income", "15", "Other Income", "income", True, True, False, None, True),
    ("finance_income", None, "Finance Income", "income", None, None, None, None, True),
    ("other_comprehensive_income", None, "Other Comprehensive Income", "income", None, None, None, None, True),
    # ── expense ─────────────────────────────────────────────────────────────
    ("expense", "16", "Expense", "expense", True, True, True, None, True),
    ("cost_of_goods_sold", "17", "Cost Of Goods Sold", "expense", True, True, True, None, True),
    ("other_expense", "18", "Other Expense", "expense", True, True, True, None, True),
    ("manufacturing_expense", None, "Manufacturing Expense", "expense", None, None, None, None, True),
    ("impairment_expense", None, "Impairment Expense", "expense", None, None, None, None, True),
    ("depreciation_expense", None, "Depreciation Expense", "expense", None, None, None, None, True),
    ("employee_benefit_expense", None, "Employee Benefit Expense", "expense", None, None, None, None, True),
    ("lease_expense", None, "Lease Expense", "expense", None, None, None, None, True),
    ("finance_expense", None, "Finance Expense", "expense", None, None, None, None, True),
    ("tax_expense", None, "Tax Expense", "expense", None, None, None, None, True),
)

#: Asset types a purchase may be capitalised into (the purchase picker offers them).
_CAPITALISABLE = frozenset({
    "fixed_asset", "other_asset", "other_current_asset", "intangible_asset", "long_term_asset",
    "capital_work_in_progress",
})


def account_type_rows() -> list[dict[str, Any]]:
    """The 46 rows, as column dicts, in display order."""
    rows: list[dict[str, Any]] = []
    for position, (code, zoho_id, name, group, sub, opening, ze, asset_type, documented) in enumerate(_TYPES):
        rows.append({
            "code": code,
            "zoho_id": zoho_id,
            "name": name,
            "account_group": group,
            "default_normal_balance_is_debit": group in ("asset", "expense"),
            "is_sub_account_allowed": sub,
            "can_show_opening_balance": opening,
            "can_enable_in_ze": ze,
            "asset_type": asset_type,
            "is_documented": documented,
            "is_sales_eligible": group == "income",
            "is_purchase_eligible": group == "expense" or code in _CAPITALISABLE,
            "is_inventory_eligible": code == "stock",
            "sort_order": (position + 1) * 10,
        })
    return rows


# (code, name, groups, types, per_currency, description)
_PURPOSES: tuple[tuple[Any, ...], ...] = (
    ("sales", "Sales / income account", ("income",), None, False,
     "Revenue of a sale (Zoho item account_id)."),
    ("purchase", "Purchase / COGS account", ("expense", "asset"), None, False,
     "Cost of a purchase (Zoho item purchase_account_id); an asset when capitalised."),
    ("inventory_asset", "Inventory account", ("asset",), ("stock",), False,
     "Stock on hand (Zoho item inventory_account_id)."),
    ("receivable", "Accounts receivable (control)", ("asset",), ("accounts_receivable",), True,
     "Customer balances; per currency in a multi-currency organization."),
    ("payable", "Accounts payable (control)", ("liability",), ("accounts_payable",), True,
     "Vendor balances; per currency in a multi-currency organization."),
    ("customer_advance", "Customer advance", ("liability",), None, False, "Advances received from customers."),
    ("vendor_advance", "Vendor advance", ("asset",), None, False, "Advances paid to vendors."),
    ("output_tax", "Output tax", ("liability",), None, False,
     "Tax collected on sales (Zoho tax tax_account_id)."),
    ("input_tax", "Input tax", ("asset",), None, False,
     "Tax paid on purchases, recoverable (Zoho tax purchase_tax_account_id)."),
    ("tds_payable", "TDS payable", ("liability",), None, False,
     "Tax deducted at source, to be paid over (Zoho tax tds_payable_account_id)."),
    ("tds_receivable", "TDS receivable", ("asset",), None, False, "Tax deducted by customers."),
    ("tcs_payable", "TCS payable", ("liability",), None, False, "Tax collected at source."),
    ("retained_earnings", "Retained earnings", ("equity",), None, False, "Where the year's profit closes to."),
    ("opening_balance_offset", "Opening balance offset", ("equity",), None, False,
     "Balancing account for opening balances."),
    ("fx_gain_loss", "Exchange gain or loss", ("income", "expense"), None, False, "Realised and unrealised FX."),
    ("round_off", "Round-off", ("income", "expense"), None, False, "Rounding differences on documents."),
    ("discount_given", "Discount given", ("expense", "income"), None, False, "Discounts allowed to customers."),
    ("discount_received", "Discount received", ("income", "expense"), None, False,
     "Discounts received from vendors."),
    ("cost_of_goods_sold", "Cost of goods sold", ("expense",), None, False, "Cost of inventory sold."),
    ("inventory_adjustment", "Inventory adjustment", ("expense", "income"), None, False,
     "Write-offs and gains on stock counts."),
    ("goods_in_transit", "Goods in transit", ("asset",), None, False, "Stock shipped, not yet received."),
    ("price_variance", "Purchase price variance", ("expense", "income"), None, False,
     "Standard vs actual purchase cost."),
    ("undeposited_funds", "Undeposited funds", ("asset",), None, False, "Receipts not yet banked."),
    ("employee_advance", "Employee advance", ("asset",), None, False, "Advances to employees."),
    ("prepaid_expenses", "Prepaid expenses", ("asset",), None, False, "Expenses paid in advance."),
)


def purpose_rows() -> list[dict[str, Any]]:
    return [
        {"code": code, "name": name, "allowed_groups": list(groups),
         "allowed_types": list(types) if types else None, "per_currency": per_currency,
         "description": description, "sort_order": (position + 1) * 10}
        for position, (code, name, groups, types, per_currency, description) in enumerate(_PURPOSES)
    ]


#: Organization-default purposes: every purpose may be set on the organization (the end of the chain).
ORGANIZATION_PURPOSES: tuple[str, ...] = tuple(code for code, *_ in _PURPOSES)

#: What a tax component posts to.
TAX_COMPONENT_PURPOSES: tuple[str, ...] = ("output_tax", "input_tax", "tds_payable")

__all__ = [
    "ORGANIZATION_PURPOSES",
    "TAX_COMPONENT_PURPOSES",
    "account_type_rows",
    "purpose_rows",
]
