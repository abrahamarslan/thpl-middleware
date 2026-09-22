"""Currency ↔ Zoho field rules (docs/zoho-docs-md/currency.md).

Each row records which way the field is allowed to travel, and the direction is
not a stylistic choice — it is what the Zoho contract says:

| field              | direction | why                                                      |
|--------------------|-----------|----------------------------------------------------------|
| ``currency_code``  | both      | required on create; the business key we match sources on  |
| ``currency_format``| both      | required on create                                        |
| ``currency_symbol``| both      | optional argument on create and update                    |
| ``price_precision``| both      | optional argument on create and update                    |
| ``currency_name``  | **in**    | Zoho COMPUTES it ("AUD- Australian Dollar"); sending it back is meaningless |
| ``is_base_currency``| **in**   | set by organization settings, not by this endpoint        |
| ``exchange_rate``  | **in**    | a cache here; the rate is written through /exchangerates   |
| ``effective_date`` | **in**    | ditto — it belongs to a rate, not to the currency          |

``currency_id`` is deliberately absent: identity lives in the crosswalk
(``sync.sync_records.external_id``), not in a column on the canonical row.
"""

from app.modules.sync.translation import Direction, FieldSpec as F

CURRENCY_FIELDS: list[F] = [
    F(external="currency_code", local="currency_code", codec="str",
      direction=Direction.BOTH, required_on_create=True),
    F(external="currency_format", local="currency_format", codec="str",
      direction=Direction.BOTH, required_on_create=True),
    F(external="currency_symbol", local="currency_symbol", codec="str",
      direction=Direction.BOTH),
    F(external="price_precision", local="price_precision", codec="int",
      direction=Direction.BOTH),
    F(external="currency_name", local="currency_name", codec="str",
      direction=Direction.IN),
    F(external="is_base_currency", local="is_base_currency", codec="bool",
      direction=Direction.IN),
    F(external="exchange_rate", local="exchange_rate", codec="money",
      direction=Direction.IN),
    F(external="effective_date", local="effective_date", codec="zoho_date",
      direction=Direction.IN),
]

#: Rate rows, from ``/settings/currencies/{id}/exchangerates`` and from the
#: scalar pair carried on a currency payload. ``rate`` and ``effective_date``
#: are the only writable arguments Zoho documents.
EXCHANGE_RATE_FIELDS: list[F] = [
    F(external="rate", local="rate", codec="money", direction=Direction.BOTH,
      required_on_create=True),
    F(external="effective_date", local="effective_date", codec="zoho_date",
      direction=Direction.BOTH),
]

__all__ = ["CURRENCY_FIELDS", "EXCHANGE_RATE_FIELDS"]
