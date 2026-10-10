"""Price lists (Zoho's API calls them pricebooks) — organization-scoped, Zoho-synced, read-only.

    pricing.price_lists               ENTITY  one price list of one organization (Zoho crosswalk)
    pricing.price_list_items          ENTITY  an item's entry in a per_item list (unit rate / brackets parent)
    pricing.price_list_item_brackets  ENTITY  a volume list's quantity bracket

Zoho adapter: ``zoho/`` (module ``price_lists``, endpoint ``/pricebooks``; items projected from the
detail document). Quotes: ``service.quote``. Docs: docs/implementation-plan/price-lists-module.md.
"""
