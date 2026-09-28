"""Categories & taxonomies (``core`` schema, package-by-feature).

    enums.py model.py tree.py schema.py crud.py service.py api.py   the feature
    ../entities/                                                    shared core registry + vocabularies
    zoho/                                                           Zoho adapter (phase 3)

HTTP: /api/taxonomies, /api/categories, /api/categorizables.

An organization-scoped taxonomy tree with a per-taxonomy whitelist of
categorisable entity types, plus a polymorphic, temporally-windowed assignment
table validated by ``core.entity_types`` / ``core.assert_entity_exists``.
Categories are Zoho-synced (phase 3).
"""

from app.modules.categories.model import Category, Categorizable, Taxonomy, TaxonomyEntityType

__all__ = ["Category", "Categorizable", "Taxonomy", "TaxonomyEntityType"]
