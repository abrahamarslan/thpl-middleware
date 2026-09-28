"""HasCustomFieldsMixin — bind custom-field values to any model with one line.

Read path: ``selectinload(Model.custom_field_values)`` eager-loads every value
for a result set in ONE extra query (no N+1). Write path: strictly through
``custom_fields.service.set_value`` / ``sync_values`` — the relationship is
``viewonly`` because mutating it in async SQLAlchemy triggers implicit lazy
loads that crash with ``MissingGreenlet``.

The owner class declares which registered ``core.entity_types`` code it is::

    class Vehicle(IntPKMixin, OrgEntityMixin, HasCustomFieldsMixin, Base):
        custom_fields_owner_type = "vehicle"   # a row in core.entity_types

Without that attribute the mapper fails loudly at configuration time, which is
what you want: a custom-field relationship with no owner type is meaningless.
"""

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.custom_fields.model import FieldValue


class HasCustomFieldsMixin:
    #: The ``core.entity_types.code`` this model's values carry. Subclasses set it.
    custom_fields_owner_type: str

    @declared_attr
    def custom_field_values(cls):  # noqa: N805
        return relationship(
            FieldValue,
            primaryjoin=lambda: and_(
                cls.id == foreign(FieldValue.owner_id),
                FieldValue.owner_type_code == cls.custom_fields_owner_type,
                # The global soft-delete filter reaches here too, but the join is
                # explicit for symmetry with HasDocumentsMixin.
                FieldValue.deleted_at.is_(None),
            ),
            viewonly=True,
            order_by="FieldValue.field_definition_id",
        )