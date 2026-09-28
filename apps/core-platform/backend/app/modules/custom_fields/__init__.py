"""Custom fields (schema ``extfields``) — a typed, registry-driven key/value store.

    enums.py model.py schema.py crud.py service.py api.py   the feature
    ../entities/                                            the shared core.entity_types registry (owner types)

HTTP: /api/custom-fields. Any registered entity type can carry fields defined
in ``field_definitions`` and answered in ``field_values``; new fields and owner
types are rows, not migrations. See docs/MODULES.md.
"""

from app.modules.custom_fields.model import DataType, FieldDefinition, FieldValue

__all__ = ["DataType", "FieldDefinition", "FieldValue"]