"""Pure packaging-hierarchy arithmetic — no SQL, no session (plan 02 §3).

Every function takes already-loaded levels (``ItemUnit``-shaped objects: ``id``, ``base_factor``,
``is_base``, ``is_sellable``, ``valid_to``, ``unit.code``) so services, the line contract and tests share one
implementation. The SQL twin for reports is ``catalogue.convert_quantity()``.

Rules:
* quantities are ``Decimal`` — never floats;
* ``to_base`` refuses a result with more decimals than the base unit allows (0.33 of a 10-piece bottle
  when pieces have 0 decimals) — a fraction of an indivisible unit is a data error, not a rounding choice;
* ``breakdown`` is a LOGICAL breakdown (coarsest-first, greedy, current levels only) — it does not know
  which physical carton is open (handling units, plan 02 §7).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Protocol

from app.common.exception.errors import AppError


class FractionalBaseQuantityError(AppError):
    status_code = 422
    code = "fractional_base_quantity"


class LevelLike(Protocol):
    id: int
    base_factor: Decimal
    is_base: bool
    valid_to: dt.date | None


def _quantum(decimal_places: int) -> Decimal:
    return Decimal(1).scaleb(-decimal_places)


def to_base(qty: Decimal, level: LevelLike, *, base_decimal_places: int = 6) -> Decimal:
    """``qty`` of ``level`` in base units, exact to the base unit's decimals (else 422)."""
    raw = Decimal(qty) * Decimal(level.base_factor)
    rounded = raw.quantize(_quantum(base_decimal_places), rounding=ROUND_HALF_EVEN)
    if rounded != raw:                  # numeric comparison: 10 == 10.000000
        raise FractionalBaseQuantityError(
            f"{qty} × {level.base_factor} = {raw} base units, but the base unit allows {base_decimal_places} decimals",
            data={"quantity": str(qty), "base_factor": str(level.base_factor), "decimal_places": base_decimal_places},
        )
    return rounded


def convert(qty: Decimal, from_level: LevelLike, to_level: LevelLike) -> Decimal:
    """``qty`` of one level expressed in another level of the same item (may be fractional)."""
    return Decimal(qty) * Decimal(from_level.base_factor) / Decimal(to_level.base_factor)


def current(levels: Iterable[Any], *, on: dt.date | None = None) -> list[Any]:
    """Levels in force on ``on`` (default today): not retired, not deleted."""
    day = on or dt.date.today()
    return [lv for lv in levels
            if getattr(lv, "deleted_at", None) is None and (lv.valid_to is None or lv.valid_to > day)]


def breakdown(qty_base: Decimal, levels: Sequence[Any], *, sellable_only: bool = False) -> list[tuple[Any, Decimal]]:
    """Greedy coarsest-first split of a base quantity: 995 → [(CTN, 1), (BTL, 3), (PCS, 5)].

    Uses current levels only (``sellable_only`` narrows to sellable ones but always keeps the base level so
    the remainder is never lost). Levels with a fractional factor are skipped (they cannot hold integers).
    """
    candidates = [lv for lv in current(levels) if lv.is_base or not sellable_only or getattr(lv, "is_sellable", True)]
    candidates.sort(key=lambda lv: Decimal(lv.base_factor), reverse=True)
    remaining = Decimal(qty_base)
    out: list[tuple[Any, Decimal]] = []
    for level in candidates:
        factor = Decimal(level.base_factor)
        if factor <= 0 or (factor != factor.to_integral_value() and not level.is_base):
            continue
        if level.is_base:
            if remaining:
                out.append((level, remaining))
            remaining = Decimal(0)
            break
        count, remaining = divmod(remaining, factor)
        if count:
            out.append((level, count))
    if remaining:                       # no base level loaded: report what is left in base units
        out.append((None, remaining))
    return out


# ── GS1 / ISBN check digits ──────────────────────────────────────────────────

def _gs1_ok(digits: str) -> bool:
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _isbn10_ok(code: str) -> bool:
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(code))
    return total % 11 == 0


def check_digit_ok(kind: str, value: str) -> bool:
    """Validate the check digit of GTIN-8/12/13/14, EAN, UPC and ISBN-10/13. Other kinds pass."""
    code = "".join(value.split()).upper()
    if kind in ("gtin", "ean", "upc"):
        return code.isdigit() and len(code) in (8, 12, 13, 14) and _gs1_ok(code)
    if kind == "isbn":
        if len(code) == 13 and code.isdigit():
            return _gs1_ok(code)
        if len(code) == 10 and code[:9].isdigit() and (code[9].isdigit() or code[9] == "X"):
            return _isbn10_ok(code)
        return False
    return True


__all__ = ["FractionalBaseQuantityError", "breakdown", "check_digit_ok", "convert", "current", "to_base"]
