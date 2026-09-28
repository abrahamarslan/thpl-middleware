"""HasCategoriesMixin — bind categories to any model with one line.

Read path: ``selectinload(Model.categories)`` eager-loads every live, currently
valid assignment in ONE extra query (no N+1). ``lazy="raise_on_sql"`` is the
N+1 firewall: an accidental attribute access without the explicit eager load
raises instead of silently issuing SQL under ``AsyncSession``.

Write path: strictly via ``categories.service`` / ``POST /api/categorizables``
(the ``tags.sync_entity_tags`` pattern). The relationship is ``viewonly``
because mutating a secondary relationship triggers implicit lazy loads that
crash async SQLAlchemy with ``MissingGreenlet``.

The pivot's ``categorizable_type`` is a ``core.entity_types.code`` (lowercase,
snake_case). A model may set ``__categorizable_type__`` explicitly; otherwise
the value is derived from the class name (``FleetPartner`` → ``fleet_partner``).
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.categories.model import Categorizable, Category

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def categorizable_type_of(model: type) -> str:
    explicit = getattr(model, "__categorizable_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasCategoriesMixin:
    @declared_attr
    def categories(cls):  # noqa: N805
        pivot = Categorizable.__table__
        return relationship(
            Category,
            secondary=pivot,
            primaryjoin=lambda: and_(
                cls.id == foreign(pivot.c.categorizable_id),
                pivot.c.categorizable_type == categorizable_type_of(cls),
                # The global soft-delete filter does not reach a secondary table.
                pivot.c.deleted_at.is_(None),
                pivot.c.valid_to.is_(None),
            ),
            secondaryjoin=lambda: foreign(pivot.c.category_id) == Category.id,
            viewonly=True,
            lazy="raise_on_sql",
            order_by=(pivot.c.sort_order.asc(), Category.id.asc()),
        )


__all__ = ["HasCategoriesMixin", "categorizable_type_of"]
