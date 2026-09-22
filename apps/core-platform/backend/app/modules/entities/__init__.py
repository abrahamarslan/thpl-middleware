"""Entity registry (``core`` schema) — entity types and polymorphic aliases.

    model.py schema.py crud.py service.py api.py   the feature
    enums.py                                       shared ``core`` vocabularies

HTTP: /api/entities. The ``brands`` and ``manufacturers`` packages import
``CORE_SCHEMA`` / ``MasterOwnerType`` from here; ``core.entity_types`` is the
catalogue their rows register in so ``core.entity_aliases`` can validate a
polymorphic target at COMMIT.
"""

from app.modules.entities.model import EntityAlias, EntityType

__all__ = ["EntityAlias", "EntityType"]
