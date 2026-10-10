"""Zoho Books ``/contacts`` → ``party.parties`` field rules (docs/zoho-docs-md/contact.md + live probe 2026-10-08).

Zoho's names on the left (it says *contact*), ours on the right (*party*). Only scalar party columns are
here; everything with structure is projected by ``hooks.py`` into the hub that owns it:

    contact_persons[]                         → party.contact_persons (+ crosswalk contact_persons)
    billing_address / shipping_address / addresses[]  → geo.places + geo.place_links
    tax_info_list[] / gst_no / pan_no / udyam_* / vat_reg_no / tax_reg_no → tax.tax_registrations
    tax_id / tax_exemption_id                 → tax.tax_assignments
    account_id                                → accounting.account_assignments (receivable / payable)
    custom_fields[]                           → extfields
    payment_terms_id                          → party.payment_terms (learned)
    owner_id                                  → zoho_users
    primary_contact_id                        → party.parties.primary_contact_person_id
    cf_merged_customer_ids                    → crosswalk merge redirect
    cf_location_latitude / _longitude         → the billing / shipping place's coordinates (plausible only)

Never stored as columns: balances (volatile below — a balance moving is not the party changing),
derived displays (currency_code, tax_name, pricebook_name …), Zoho-internal UI state (locks,
approvals, templates, portal counters), CRM linkage; the raw document keeps them.
"""

from app.modules.sync.translation import Direction, FieldSpec as F, PayloadShape

IN, BOTH = Direction.IN, Direction.BOTH

FIELDS: list[F] = [
    F(external="contact_name", local="name", codec="str", direction=BOTH, required_on_create=True),
    F(external="company_name", local="company_name", codec="str", direction=BOTH),
    F(external="contact_number", local="contact_number", codec="str", direction=BOTH),
    F(external="legal_name", local="legal_name", codec="str", direction=BOTH),
    F(external="trader_name", local="trade_name", codec="str", direction=BOTH),
    F(external="contact_salutation", local="salutation", codec="str", direction=BOTH),
    F(external="first_name", local="first_name", codec="str", direction=BOTH),
    F(external="last_name", local="last_name", codec="str", direction=BOTH),
    F(external="designation", local="designation", codec="str", direction=BOTH),
    F(external="department", local="department", codec="str", direction=BOTH),
    F(external="contact_type", local="party_type", codec="str", direction=BOTH, required_on_create=True),
    F(external="customer_sub_type", local="customer_sub_type", codec="str", direction=BOTH),
    F(external="source", local="source", codec="str", direction=IN),
    # Not in the documented attributes; on every live contact (audit 2026-10-09: "direct_sales").
    F(external="sales_channel", local="sales_channel", codec="str", direction=BOTH),
    F(external="language_code", local="language_code", codec="str", direction=BOTH),
    F(external="is_bcy_only_contact", local="is_base_currency_only", codec="bool", direction=IN),
    F(external="payment_terms", local="payment_terms", codec="int", direction=BOTH),
    F(external="payment_terms_label", local="payment_terms_label", codec="str", direction=BOTH),
    F(external="credit_limit", local="credit_limit", codec="decimal", direction=BOTH),
    F(external="is_taxable", local="is_taxable", codec="bool", direction=BOTH),
    F(external="place_of_contact", local="place_of_supply", codec="str", direction=BOTH),
    F(external="gst_treatment", local="gst_treatment", codec="str", direction=BOTH),
    F(external="contact_category", local="contact_category", codec="str", direction=IN),
    F(external="email", local="email", codec="str", direction=BOTH),
    F(external="phone", local="phone", codec="str", direction=BOTH),
    F(external="mobile", local="mobile", codec="str", direction=BOTH),
    F(external="website", local="website", codec="str", direction=BOTH),
    F(external="facebook", local="facebook", codec="str", direction=BOTH),
    F(external="twitter", local="twitter", codec="str", direction=BOTH),
    F(external="is_sms_enabled", local="is_sms_enabled", codec="bool", direction=IN),
    F(external="payment_reminder_enabled", local="payment_reminder_enabled", codec="bool", direction=IN),
    F(external="portal_status", local="portal_status", codec="str", direction=IN),
    F(external="is_consent_agreed", local="consent_agreed", codec="bool", direction=IN),
    F(external="consent_date", local="consent_at", codec="zoho_datetime", direction=IN),
    F(external="has_transaction", local="has_transaction", codec="bool", direction=IN),
    F(external="is_associated_to_branch", local="is_associated_to_branch", codec="bool", direction=IN),
    F(external="notes", local="notes", codec="str", direction=BOTH, shapes=(PayloadShape.DETAIL,)),
    F(external="created_time", local="source_created_at", codec="zoho_datetime", direction=IN),
    # Zoho changes activity through POST /contacts/{id}/active|inactive, never the body: IN only.
    F(external="status", local="status", codec="str", direction=IN),
]

#: Keys that change without the party changing — never part of the no-op hash.
VOLATILE_KEYS: list[str] = [
    "*_formatted", "page_context", "instrumentation",
    "outstanding_*", "unused_*", "opening_balance_amount", "opening_balance_amount_bcy",
    "credit_limit_exceeded_amount", "customer_currency_summaries", "vendor_currency_summaries",
    "portal_receipt_count",
]

__all__ = ["FIELDS", "VOLATILE_KEYS"]
