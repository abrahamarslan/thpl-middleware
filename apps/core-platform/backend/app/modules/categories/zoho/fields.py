"""Zoho Books category → ``core.categories`` field rules (docs/zoho-docs-md/categories.md).

The list row carries the tree fields; the detail document adds the SEO block,
``custom_fields`` and ``category_tax_preferences`` (the raw document keeps all
three on ``sync.sync_records``). Zoho's ``url`` is our ``slug``; ``visibility``
is Zoho's boolean, landing on ``is_visible``. Columns with no Zoho counterpart
(``image_url``, ``thumbnail_url``, ``banner_url``, ``icon_*``, ``settings``,
``metadata_`` …) simply do not appear here — they stay ours.

Not in the field map, deliberately:

  * ``parent_category_id`` — resolved through the crosswalk in
    ``hooks.post_upsert``. It cannot be a ``ReferenceRule``: a category names a
    row of ITS OWN module, usually one that arrives in the same page, and the
    page's reference preload runs before any row of that page exists. Zoho also
    sends ``-1`` for "no parent".
  * ``depth`` / ``has_active_items`` — local tree bounds are owned by
    ``tree.py``; the item counter is deferred (plan D7).
  * ``category_tax_preferences`` — a list of ``{tax_specification, tax_id}``
    pairs. It needs a child table keyed to ``tax.tax_components``, which is a
    design decision of its own (docs/implementation-plan/categories-zoho-sync-review.md §5).
"""

from app.modules.categories.zoho import codecs as _codecs  # noqa: F401 — registers "csv_list"
from app.modules.sync.translation import Direction, FieldSpec as F

BOTH = Direction.BOTH

FIELDS: list[F] = [
    # identity / display
    F(external="name", local="name", codec="str", direction=BOTH, required_on_create=True),
    F(external="url", local="slug", codec="str", direction=BOTH, required_on_create=True),
    F(external="description", local="description", codec="str", direction=BOTH),
    # menu / ordering (Zoho sibling_order ↔ our position)
    F(external="visibility", local="is_visible", codec="bool", direction=BOTH),
    F(external="show_in_menu", local="show_in_menu", codec="bool", direction=BOTH),
    F(external="sibling_order", local="position", codec="int", direction=BOTH),
    # SEO (detail document only)
    F(external="seo_title", local="meta_title", codec="str", direction=BOTH),
    F(external="seo_keyword", local="meta_keywords", codec="csv_list", direction=BOTH),
    F(external="seo_description", local="meta_description", codec="str", direction=BOTH),
    # ONDC classification
    F(external="ondc_category_type", local="ondc_category_type", codec="str", direction=BOTH),
]

__all__ = ["FIELDS"]
