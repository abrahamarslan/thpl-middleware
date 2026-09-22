"""Tax-specific codecs, registered with the shared translation layer on import.

Each is a ``decode`` written for one thing the generic ``str`` / ``decimal``
codecs cannot say — and each REJECTS rather than coerces. A value a CHECK
constraint would refuse is dropped here (a ``Decoded.warnings`` entry, the record
survives) instead of reaching the database, where it would fail the whole page
flush and force the one-by-one fallback.

The names are the vocabulary of ``mappings.py``:

    lower_str        ``lower|empty_to_null``
    tax_type         ``map_tax_type``
    specific_type    ``canonical_specific_type``
    tax_specification ``lower|empty_to_null`` restricted to inter / intra
    decimal_rate     ``decimal_rate``
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.sync.translation import CODECS, Codec, register_codec
from app.modules.taxes.enums import TaxSpecification, TaxType

#: NUMERIC(7,4) holds up to 999.9999 — anything else is not a tax rate.
_RATE_CEILING = Decimal(1000)


def _dec_lower_str(value: Any) -> str | None:
    text = str(value).strip().lower()
    return text or None


def _dec_tax_type(value: Any) -> str | None:
    """``tax`` / ``compound_tax`` / ``tax_group`` → canonical; anything else is refused.

    The legacy numeric ``tax_type`` (0 / 2) served by ``default_taxes`` is refused
    too, on purpose: which integer means which shape has not been verified, and
    guessing would silently mislabel a group as a leaf (or the reverse). The raw
    integer is preserved in ``source_default_tax_type_code`` for exactly this.
    """
    if isinstance(value, int | float):          # bool is an int
        raise ValueError(f"numeric tax_type {value!r} has no verified mapping")
    text = str(value).strip().lower()
    if not text:
        return None
    if text not in {member.value for member in TaxType}:
        raise ValueError(f"unknown tax_type {value!r}")
    return text


def _dec_specific_type(value: Any) -> str | None:
    """trim + lower + empty → NULL, and Zoho's generic sentinel ``"tax"`` → NULL.

    A specific leg is cgst / sgst / igst / …; ``"tax"`` says "no particular leg"
    and a group has none, so neither is stored.
    """
    text = str(value).strip().lower()
    return None if text in ("", "tax") else text


def _dec_tax_specification(value: Any) -> str | None:
    text = str(value).strip().lower()
    if not text:
        return None
    if text not in {member.value for member in TaxSpecification}:
        raise ValueError(f"unknown tax_specification {value!r}")
    return text


def _dec_decimal_rate(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    rate = Decimal(str(value).strip())
    if not (Decimal(0) <= rate < _RATE_CEILING):        # NaN raises InvalidOperation here — also a refusal
        raise ValueError(f"rate {value!r} outside 0..{_RATE_CEILING}")
    return rate


def _enc_str(value: Any) -> Any:
    return None if value is None else str(value)


def _enc_number(value: Any) -> Any:
    return CODECS["decimal"].encode(value)


for _codec in (
    Codec("lower_str", _dec_lower_str, _enc_str),
    Codec("tax_type", _dec_tax_type, _enc_str),
    Codec("specific_type", _dec_specific_type, _enc_str),
    Codec("tax_specification", _dec_tax_specification, _enc_str),
    Codec("decimal_rate", _dec_decimal_rate, _enc_number),
):
    register_codec(_codec)
