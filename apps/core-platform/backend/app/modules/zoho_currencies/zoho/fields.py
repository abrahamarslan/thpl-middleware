"""Currencies field map (docs/zoho-docs-md/currency.md). Pull-only: nothing outbound."""

from app.modules.zoho.sync.config import FieldMapping as F

FIELDS: list[F] = [
    F(zoho="currency_code", local="currency_code", transform="str", outbound=False),
    F(zoho="currency_name", local="currency_name", transform="str", outbound=False),
    F(zoho="currency_symbol", local="currency_symbol", transform="str", outbound=False),
    F(zoho="currency_format", local="currency_format", transform="str", outbound=False),
    F(zoho="price_precision", local="price_precision", transform="int", outbound=False),
    F(zoho="is_base_currency", local="is_base_currency", transform="bool", outbound=False),
    F(zoho="exchange_rate", local="exchange_rate", transform="decimal", outbound=False),
    F(zoho="effective_date", local="effective_date", transform="zoho_date", outbound=False),
]
