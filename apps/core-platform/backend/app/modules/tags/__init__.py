"""Tags module — polymorphic, multilingual tagging for any entity.

Attach tags to any model by inheriting HasTagsMixin (read path) and mutating
through the /api/tags/sync endpoint or tags.crud.sync_entity_tags (write
path). See docs/MODULES.md.
"""
