"""Zoho organization → organization node field map (docs/zoho-docs-md/organizations.md).

Only profile columns are Zoho-owned. Structural columns (org_code, org_type,
parent, status, hierarchy) are never written by the sync.
"""

from app.modules.zoho.sync.config import FieldMapping as F

FIELDS: list[F] = [
    # Identity & contact
    F(zoho="name", local="name", transform="str"),
    F(zoho="contact_name", local="contact_name", transform="str"),
    F(zoho="email", local="email", transform="str"),
    F(zoho="phone", local="phone", transform="str"),
    F(zoho="website", local="website", transform="str"),
    # Zoho account state
    F(zoho="is_default_org", local="is_default_org", transform="bool"),
    F(zoho="is_org_active", local="is_org_active", transform="bool"),
    F(zoho="user_role", local="user_role", transform="str"),
    F(zoho="user_status", local="user_status", transform="str"),
    F(zoho="account_created_date", local="account_created_date", transform="zoho_date"),
    F(zoho="industry_type", local="industry_type", transform="str"),
    F(zoho="industry_size", local="industry_size", transform="str"),
    # Locale / formats
    F(zoho="language_code", local="language_code", transform="str"),
    F(zoho="time_zone", local="time_zone", transform="str"),
    F(zoho="date_format", local="date_format", transform="str"),
    F(zoho="field_separator", local="field_separator", transform="str"),
    # Documented as 0–11, sent by the live API as "april": month_index takes both (ERRORS E34).
    F(zoho="fiscal_year_start_month", local="fiscal_year_start_month", transform="month_index"),
    F(zoho="tax_group_enabled", local="tax_group_enabled", transform="bool"),
    # Currency (Zoho ids; currency_id → zoho_currencies.id is resolved by hooks.link_currency)
    F(zoho="currency_id", local="zoho_currency_id", transform="str"),
    F(zoho="currency_code", local="currency_code", transform="str"),
    F(zoho="currency_symbol", local="currency_symbol", transform="str"),
    F(zoho="currency_format", local="currency_format", transform="str"),
    F(zoho="price_precision", local="price_precision", transform="int"),
    # Nested billing address -> flat columns
    F(zoho="address.street_address1", local="address_street1", transform="str"),
    F(zoho="address.street_address2", local="address_street2", transform="str"),
    F(zoho="address.city", local="address_city", transform="str"),
    F(zoho="address.state", local="address_state", transform="str"),
    F(zoho="address.country", local="address_country", transform="str"),
    F(zoho="address.zip", local="address_zip", transform="str"),
]
