"""Locations field map (docs/zoho-docs-md/locations.md). Pull-only."""

from app.modules.zoho.sync.config import FieldMapping as F

FIELDS: list[F] = [
    F(zoho="location_name", local="location_name", transform="str", outbound=False),
    F(zoho="type", local="type", transform="str", outbound=False),
    F(zoho="status", local="zoho_status", transform="str", outbound=False),
    F(zoho="is_primary", local="is_primary", transform="bool", outbound=False),
    F(zoho="email", local="email", transform="str", outbound=False),
    F(zoho="phone", local="phone", transform="str", outbound=False),
    F(zoho="parent_location_id", local="parent_location_id", transform="str", outbound=False),
    F(zoho="tax_settings_id", local="tax_settings_id", transform="str", outbound=False),
    F(zoho="auto_number_generation_id", local="auto_number_generation_id", transform="str", outbound=False),
    F(zoho="is_all_users_selected", local="is_all_users_selected", transform="bool", outbound=False),
    # Lists stored as-is (JSONB); a child table can replace them when something joins on them.
    F(zoho="associated_series_ids", local="associated_series_ids", outbound=False),
    F(zoho="associated_users", local="associated_users", outbound=False),
    # Nested address -> flat columns
    F(zoho="address.attention", local="address_attention", transform="str", outbound=False),
    F(zoho="address.street_address1", local="address_street1", transform="str", outbound=False),
    F(zoho="address.street_address2", local="address_street2", transform="str", outbound=False),
    F(zoho="address.city", local="address_city", transform="str", outbound=False),
    F(zoho="address.state", local="address_state", transform="str", outbound=False),
    F(zoho="address.state_code", local="address_state_code", transform="str", outbound=False),
    F(zoho="address.country", local="address_country", transform="str", outbound=False),
]
