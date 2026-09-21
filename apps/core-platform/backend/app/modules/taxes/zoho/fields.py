"""Taxes field map (docs/zoho-docs-md/taxes.md, list response). Pull-only."""

from app.modules.zoho.sync.config import FieldMapping as F

FIELDS: list[F] = [
    F(zoho="tax_name", local="tax_name", transform="str", outbound=False),
    F(zoho="tax_percentage", local="tax_percentage", transform="decimal", outbound=False),
    F(zoho="tax_type", local="tax_type", transform="str", outbound=False),
    F(zoho="tax_specific_type", local="tax_specific_type", transform="str", outbound=False),
    F(zoho="tax_factor", local="tax_factor", transform="str", outbound=False),
    F(zoho="tax_authority_id", local="tax_authority_id", transform="str", outbound=False),
    F(zoho="tax_authority_name", local="tax_authority_name", transform="str", outbound=False),
    F(zoho="is_value_added", local="is_value_added", transform="bool", outbound=False),
    F(zoho="is_default_tax", local="is_default_tax", transform="bool", outbound=False),
    F(zoho="is_editable", local="is_editable", transform="bool", outbound=False),
    F(zoho="country", local="country", transform="str", outbound=False),
    F(zoho="country_code", local="country_code", transform="str", outbound=False),
    F(zoho="tax_account_id", local="tax_account_id", transform="str", outbound=False),
    F(zoho="purchase_tax_account_id", local="purchase_tax_account_id", transform="str", outbound=False),
    F(zoho="output_tax_account_name", local="output_tax_account_name", transform="str", outbound=False),
    F(zoho="purchase_tax_account_name", local="purchase_tax_account_name", transform="str", outbound=False),
]
