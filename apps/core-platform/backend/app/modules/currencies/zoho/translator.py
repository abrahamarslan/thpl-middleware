"""Currency ↔ Zoho translators — the module's half of the anti-corruption layer.

Two translators, because Zoho has two resources: the currency itself and its
effective-dated exchange rates. They are declared separately rather than as one
nested spec, because they have separate endpoints, separate write arguments and
separate lifecycles — which is exactly when a second translator is cheaper than
a bigger one.

The only irreducible bit is that a currency payload carries a rate *inline* as
two scalars (``exchange_rate`` + ``effective_date``) while the rates endpoint
returns them as rows. ``CurrencyTranslator`` normalises that: whatever shape it
arrives in, the adapter's hook receives rate rows.
"""

from __future__ import annotations

from typing import Any

from app.modules.currencies.zoho.fields import CURRENCY_FIELDS, EXCHANGE_RATE_FIELDS
from app.modules.sync.translation import (
    Decoded,
    FieldTranslator,
    PayloadShape,
    WriteIntent,
)

#: Rate rows produced by a currency payload are tagged with their provenance so
#: the projection can tell "Zoho told us this" from an operator's entry.
RATE_SOURCE = "zoho"


class ExchangeRateTranslator(FieldTranslator):
    """``/settings/currencies/{id}/exchangerates`` rows ↔ ``currency.exchange_rates``."""


class CurrencyTranslator(FieldTranslator):
    """``/settings/currencies`` ↔ ``currency.currencies``.

    Adds one thing to the declarative base: the inline rate. A currency payload
    that carries ``exchange_rate`` (and usually ``effective_date``) is also
    telling us a rate, and the rate's home is ``currency.exchange_rates`` — the
    column on the currency row is only a cache.
    """

    def __init__(self, module: str) -> None:
        super().__init__(module, CURRENCY_FIELDS)
        self.rates = ExchangeRateTranslator(f"{module}.exchange_rates", EXCHANGE_RATE_FIELDS)

    def decode(self, payload: dict, *, shape: PayloadShape = PayloadShape.DETAIL) -> Decoded:
        decoded = super().decode(payload, shape=shape)

        # The inline rate: present on both index and detail currency payloads.
        # Absent (or rateless) payloads simply produce no child rows — never a
        # row with a NULL rate, which would look like a real quote of zero.
        rate = decoded.values.get("exchange_rate")
        if rate is not None:
            decoded.children["exchange_rates"] = [{
                "rate": rate,
                "effective_date": decoded.values.get("effective_date"),
                "rate_source": RATE_SOURCE,
            }]
        return decoded

    def decode_rates(self, rows: list[dict], *, shape: PayloadShape = PayloadShape.DETAIL) -> list[dict[str, Any]]:
        """Translate a ``/exchangerates`` collection into rate rows."""
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            values = self.rates.decode(row, shape=shape).values
            if values.get("rate") is None:
                continue
            out.append({**values, "rate_source": RATE_SOURCE})
        return out

    def encode_rate(self, rate_row: Any, *, intent: WriteIntent = WriteIntent.CREATE) -> dict:
        """Our rate row → the body Zoho's exchange-rate endpoints expect."""
        return self.rates.encode(rate_row, intent=intent)


#: One instance per module; translators are stateless and pure.
CURRENCY_TRANSLATOR = CurrencyTranslator("currencies")

#: Canonical columns Zoho feeds. A local edit to one of these would be silently
#: overwritten by the next sync, so the API refuses it on a linked row. Derived
#: from the field rules rather than hand-listed, so the two can never drift.
ZOHO_OWNED_CURRENCY_FIELDS: frozenset[str] = frozenset(CURRENCY_TRANSLATOR.readable)

__all__ = [
    "CURRENCY_TRANSLATOR",
    "RATE_SOURCE",
    "ZOHO_OWNED_CURRENCY_FIELDS",
    "CurrencyTranslator",
    "ExchangeRateTranslator",
]
