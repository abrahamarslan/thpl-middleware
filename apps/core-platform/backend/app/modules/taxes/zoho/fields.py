"""Tax ↔ Zoho field rules — three resources, three maps.

    TAX_FIELDS         GET /settings/taxes[/{id}]          → tax.tax_components (leaf rows)
    TAX_GROUP_FIELDS   GET /settings/taxgroups/{id}        → tax.tax_components (group rows)
    EXEMPTION_FIELDS   GET /settings/taxexemptions[/{id}]  → tax.tax_exemptions

Direction is the load-bearing column (docs/SYNC_ARCHITECTURE.md §4). ``BOTH`` is
reserved for attributes Zoho documents as create/update ARGUMENTS
(docs/zoho-docs-md/taxes.md); everything the source merely returns — and
everything only seen in captured payloads, whose outbound acceptance has not been
verified (``pending_verification`` in mappings.py) — is ``IN``, so
``translator.encode`` can never send an unverified attribute upstream.

The ``update_recurring_invoice`` / ``update_draft_invoice`` / … create arguments
are absent on purpose: they are request options telling Zoho what else to touch,
not attributes of a tax.

Dates use ``zoho_date`` (business day, AP7): the empty string Zoho sends for "no
date" decodes to NULL.
"""

from app.modules.sync.translation import Direction, FieldSpec as F
from app.modules.taxes.zoho import codecs as _codecs  # noqa: F401 — registers the tax codecs

IN = Direction.IN
BOTH = Direction.BOTH

TAX_FIELDS: list[F] = [
    # ── documented create/update arguments ──────────────────────────────────
    F(external="tax_name", local="tax_name", codec="str", direction=BOTH, required_on_create=True),
    F(external="tax_percentage", local="tax_percentage", codec="decimal_rate",
      direction=BOTH, required_on_create=True),
    F(external="tax_type", local="tax_type", codec="tax_type", direction=BOTH),
    F(external="tax_specific_type", local="tax_specific_type", codec="specific_type", direction=BOTH),
    F(external="tax_factor", local="tax_factor", codec="str", direction=BOTH),
    F(external="tax_authority_id", local="tax_authority_id", codec="str", direction=BOTH),
    F(external="tax_authority_name", local="tax_authority_name", codec="str", direction=BOTH),
    F(external="country_code", local="country_code", codec="str", direction=BOTH),
    F(external="purchase_tax_expense_account_id", local="purchase_tax_expense_account_id",
      codec="int", direction=BOTH),
    F(external="is_value_added", local="is_value_added", codec="bool", direction=BOTH),
    F(external="is_editable", local="is_editable", codec="bool", direction=BOTH),

    # ── returned by Zoho, documented as read-only ───────────────────────────
    F(external="country", local="country", codec="str", direction=IN),
    F(external="tds_payable_account_id", local="tds_payable_account_id", codec="str", direction=IN),
    F(external="is_default_tax", local="is_default_tax", codec="bool", direction=IN),
    F(external="tax_account_id", local="tax_account_id", codec="str", direction=IN),
    F(external="purchase_tax_account_id", local="purchase_tax_account_id", codec="str", direction=IN),
    F(external="output_tax_account_name", local="output_tax_account_name", codec="str", direction=IN),
    F(external="purchase_tax_account_name", local="purchase_tax_account_name", codec="str", direction=IN),

    # ── seen in captured payloads, not in the public docs ───────────────────
    F(external="tax_display_name", local="tax_display_name", codec="str", direction=IN),
    F(external="is_inactive", local="is_inactive", codec="bool", direction=IN),
    F(external="is_state_cess", local="is_state_cess", codec="bool", direction=IN),
    F(external="tax_specification", local="tax_specification", codec="tax_specification", direction=IN),
    F(external="diff_rate_reason", local="diff_rate_reason", codec="str", direction=IN),
    F(external="start_date", local="start_date", codec="zoho_date", direction=IN),
    F(external="end_date", local="end_date", codec="zoho_date", direction=IN),
    # An empty status is "unspecified", and status is NOT NULL: it lands as the
    # column default rather than as a NULL the database would refuse.
    F(external="status", local="status", codec="lower_str", direction=IN, default="active"),
    F(external="description", local="description", codec="str", direction=IN),
    F(external="reference_id", local="reference_id", codec="str", direction=IN),
    F(external="tax_name_formatted", local="tax_name_formatted", codec="str", direction=IN),
    # NOT mapped here: is_non_advol_tax, source_new_tax_type and
    # source_default_tax_type_code. The catalog sources them from the
    # ``default_taxes[]`` list, whose endpoint is not in docs/zoho-docs-md — they
    # are filled by that adapter, when it exists, not guessed from this payload.
]

TAX_GROUP_FIELDS: list[F] = [
    F(external="tax_group_name", local="tax_name", codec="str", direction=BOTH, required_on_create=True),
    # The group's percentage is the SUM of its members' — Zoho computes it.
    F(external="tax_group_percentage", local="tax_percentage", codec="decimal_rate", direction=IN),
    # Not a documented group attribute; captured payloads carry it. The adapter's
    # pre-hook forces 'tax_group' regardless, so a wrong value here cannot mislabel a group.
    F(external="tax_type", local="tax_type", codec="tax_type", direction=IN),
    F(external="status", local="status", codec="lower_str", direction=IN, default="active"),
    F(external="start_date", local="start_date", codec="zoho_date", direction=IN),
    F(external="end_date", local="end_date", codec="zoho_date", direction=IN),
]

EXEMPTION_FIELDS: list[F] = [
    # Documented create/update arguments (tax_exemption_code and type are required).
    F(external="tax_exemption_code", local="tax_exemption_code", codec="str",
      direction=BOTH, required_on_create=True),
    F(external="description", local="description", codec="str", direction=BOTH),
    F(external="type", local="type", codec="lower_str", direction=BOTH, required_on_create=True),
    # Captured payloads only.
    F(external="type_formatted", local="type_formatted", codec="str", direction=IN),
    F(external="exemption_name", local="exemption_name", codec="str", direction=IN),
    F(external="exemption_type", local="exemption_type", codec="lower_str", direction=IN),
    F(external="exemption_type_formatted", local="exemption_type_formatted", codec="str", direction=IN),
]

__all__ = ["EXEMPTION_FIELDS", "TAX_FIELDS", "TAX_GROUP_FIELDS"]
