"""Zoho Books ``/pricebooks`` → ``pricing.price_lists`` field rules (https://www.zoho.com/books/api/v3/pricelists/ + live probe 2026-10-08).

Zoho's names on the left (its API says *pricebook*), ours on the right (*price list*).

What each shape carries (verified live against THPL — 4 lists, every type/scheme/side present):

  * LIST row:   currency_code, currency_id, decimal_place, description, is_increase,
                last_modified_time, name, percentage, pricebook_id, pricebook_rate,
                pricebook_type, pricing_scheme, rounding_type, sales_or_purchase_type, status.
  * DETAIL:     the list's keys EXCEPT ``last_modified_time``, plus ``is_default``,
                ``pricebook_items`` and ``products``.

Not in the field map, deliberately:

  * ``pricebook_id`` — the crosswalk's ``external_id`` (+ the engine's ``zoho_id`` echo);
  * ``currency_id`` — a ``ReferenceRule`` (module ``currencies``, DEFER). Zoho sends ``""`` for a
    fixed_percentage list (= the organization's base currency); the hook clears the column then,
    because the reference planner skips a blank id rather than writing NULL;
  * ``pricebook_items`` — projected into ``pricing.price_list_items`` / ``price_list_item_brackets``
    by ``hooks.after_price_list_upsert``, from the DETAIL document only;
  * ``currency_code``, ``last_modified_time`` — display / the crosswalk's ``source_modified_at``;
  * ``products`` — always ``[]`` on THPL (undocumented); kept in the raw document only.
"""

from app.modules.sync.translation import Direction, FieldSpec as F, PayloadShape

IN, BOTH = Direction.IN, Direction.BOTH

FIELDS: list[F] = [
    F(external="name", local="name", codec="str", direction=BOTH, required_on_create=True),
    F(external="description", local="description", codec="str", direction=BOTH),
    F(external="pricebook_type", local="price_list_type", codec="str", direction=BOTH, required_on_create=True),
    F(external="sales_or_purchase_type", local="sales_or_purchase_type", codec="str", direction=BOTH,
      required_on_create=True),
    F(external="pricing_scheme", local="pricing_scheme", codec="str", direction=BOTH),   # "" → NULL
    F(external="percentage", local="percentage", codec="decimal", direction=BOTH),
    F(external="pricebook_rate", local="rate", codec="decimal", direction=IN),
    F(external="is_increase", local="is_increase", codec="bool", direction=BOTH),
    F(external="rounding_type", local="rounding_type", codec="str", direction=BOTH),
    F(external="decimal_place", local="decimal_place", codec="int", direction=BOTH),
    # Zoho changes activity through POST /pricebooks/{id}/active|inactive, never the body: IN only.
    F(external="status", local="status", codec="str", direction=IN),
    F(external="is_default", local="is_default", codec="bool", direction=IN, shapes=(PayloadShape.DETAIL,)),
]

#: Payload keys that change without the price list changing — never part of the no-op hash.
VOLATILE_KEYS: list[str] = ["*_formatted", "page_context", "instrumentation"]

__all__ = ["FIELDS", "VOLATILE_KEYS"]
