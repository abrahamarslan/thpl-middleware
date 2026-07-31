"""HasTagsMixin — bind tags to any model with one line of inheritance.

Read path: ``selectinload(Model.tags)`` eager-loads every tag for a result
set in ONE extra query (no N+1). Write path: strictly via
tags.crud.sync_entity_tags / POST /api/tags/sync — the relationship is
``viewonly`` because mutating a secondary relationship triggers implicit
lazy loads that crash async SQLAlchemy with MissingGreenlet.
"""

from sqlalchemy import String, cast
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.tags.model import Tag, Taggable


class HasTagsMixin:
    @declared_attr
    def tags(cls):  # noqa: N805
        # cast(id, String) lets Integer-PK and UUID-PK models join the same
        # String pivot column safely. Both join legs need explicit foreign()
        # annotations because the pivot's taggable_id has no real FK (it is
        # polymorphic across many tables).
        return relationship(
            Tag,
            secondary=Taggable.__table__,
            primaryjoin=lambda: (
                cast(cls.id, String) == foreign(Taggable.taggable_id)
            ) & (Taggable.taggable_type == cls.__name__),
            secondaryjoin=lambda: foreign(Taggable.tag_id) == Tag.id,
            viewonly=True,
            order_by=Tag.order_column,
        )
