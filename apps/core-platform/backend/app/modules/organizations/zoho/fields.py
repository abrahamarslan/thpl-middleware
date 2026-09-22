"""Zoho organization → organization node field rules (docs/zoho-docs-md/organizations.md).

Only the PROFILE is Zoho's. Everything structural — ``org_code``, ``org_type``,
``parent_id``, ``status``, the hierarchy columns — belongs to the tenant tree and
is never written by the sync, so it simply does not appear here.

Direction: every rule is ``IN``. The tree is ours and Zoho's organization
endpoint is not a place we write back to; the v1 outbox push was retired with
the old ``zoho_organizations`` table. Declaring that explicitly (rather than
leaving the default BOTH and relying on nobody calling ``encode``) means an
outbound payload for this module is structurally empty instead of wrong.
"""

from app.modules.sync.translation import Direction, FieldSpec as F

IN = Direction.IN

FIELDS: list[F] = [
    # Identity & contact
    F(external="name", local="name", codec="str", direction=IN),
    F(external="contact_name", local="contact_name", codec="str", direction=IN),
    F(external="email", local="email", codec="str", direction=IN),
    F(external="phone", local="phone", codec="str", direction=IN),
    F(external="website", local="website", codec="str", direction=IN),
    # Zoho account state
    F(external="is_default_org", local="is_default_org", codec="bool", direction=IN),
    F(external="is_org_active", local="is_org_active", codec="bool", direction=IN),
    F(external="user_role", local="user_role", codec="str", direction=IN),
    F(external="user_status", local="user_status", codec="str", direction=IN),
    F(external="account_created_date", local="account_created_date", codec="zoho_date", direction=IN),
    F(external="industry_type", local="industry_type", codec="str", direction=IN),
    F(external="industry_size", local="industry_size", codec="str", direction=IN),
    # Locale / formats
    F(external="language_code", local="language_code", codec="str", direction=IN),
    F(external="time_zone", local="time_zone", codec="str", direction=IN),
    F(external="date_format", local="date_format", codec="str", direction=IN),
    F(external="field_separator", local="field_separator", codec="str", direction=IN),
    # Documented as 0–11, sent by the live API as "april": month_index takes both (ERRORS E34).
    F(external="fiscal_year_start_month", local="fiscal_year_start_month",
      codec="month_index", direction=IN),
    F(external="tax_group_enabled", local="tax_group_enabled", codec="bool", direction=IN),
    # The currency REFERENCE. Zoho sends only its own id; the local FK
    # (organizations.currency_id) is resolved through the crosswalk by
    # hooks.link_currency. Keeping the raw id in its own column is what makes
    # that resolution repeatable — and repairable — without re-reading Zoho.
    F(external="currency_id", local="zoho_currency_id", codec="str", direction=IN),
    F(external="currency_code", local="currency_code", codec="str", direction=IN),
    F(external="currency_symbol", local="currency_symbol", codec="str", direction=IN),
    F(external="currency_format", local="currency_format", codec="str", direction=IN),
    F(external="price_precision", local="price_precision", codec="int", direction=IN),
    # Nested billing address -> flat columns. Only ever sent on the DETAIL
    # document, which is the reason this module fetches one.
    F(external="address.street_address1", local="address_street1", codec="str", direction=IN),
    F(external="address.street_address2", local="address_street2", codec="str", direction=IN),
    F(external="address.city", local="address_city", codec="str", direction=IN),
    F(external="address.state", local="address_state", codec="str", direction=IN),
    F(external="address.country", local="address_country", codec="str", direction=IN),
    F(external="address.zip", local="address_zip", codec="str", direction=IN),
]

__all__ = ["FIELDS"]
