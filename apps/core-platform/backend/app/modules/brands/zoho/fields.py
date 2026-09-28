"""Zoho Books brand -> ``core.brands`` field rules.

Verified live (2026-09-28) — there is no vendored doc, so nothing here is
invented, only observed: ``GET /brands`` returns ``[{brand_id, name}]`` and
``GET /brands/{id}`` returns the identical two fields, no more. That is the
whole payload; every other ``core.brands`` column (``slug``, ``code``, ``kind``,
``parent_id``, ``country_code``, ``description``, ``website_url``,
``logo_storage_key``) has no Zoho counterpart and simply does not appear here —
they stay ours, always locally editable, even on a linked row.
"""

from app.modules.sync.translation import Direction, FieldSpec as F

BOTH = Direction.BOTH

FIELDS: list[F] = [
    F(external="name", local="name", codec="str", direction=BOTH, required_on_create=True),
]

__all__ = ["FIELDS"]
