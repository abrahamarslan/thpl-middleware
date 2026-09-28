"""HasCommentsMixin — let any model carry comments with one line of inheritance.

    class Item(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasCommentsMixin, Base): ...

Read path: ``selectinload(Model.comments)`` eager-loads every live comment for a result set
in ONE extra query (no N+1); ``lazy="raise_on_sql"`` is the N+1 firewall, exactly as
``HasTagsMixin``/``HasTaxesMixin`` use it — touching the attribute without the explicit
eager load raises instead of silently issuing SQL under ``AsyncSession``.

Write path: strictly through ``comments.service`` (or ``POST /api/comments``) — the
relationship is ``viewonly`` for the same reason tags' and taxes' are (mutating a
polymorphic, no-FK relationship triggers implicit lazy loads that crash async SQLAlchemy
with ``MissingGreenlet``, and every write needs the org-scope + registry checks the
service — really the database trigger — owns).

The owner's class is its ``core.entity_types`` code, derived from the class name
(``TaxComponent`` -> ``tax_component``) unless the model sets ``__commentable_type__``.
Making the class commentable also needs a registry row —
``comments/registration.py::register_commentable_entity_type`` — which is a migration
concern, not a model one (mirrors ``taxes/mixins.py::taxable_type_of`` exactly).
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.comments.model import Comment

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def commentable_type_of(model: type) -> str:
    """The ``core.entity_types.code`` a model's comments are stored under."""
    explicit = getattr(model, "__commentable_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasCommentsMixin:
    @declared_attr
    def comments(cls):  # noqa: N805
        return relationship(
            Comment,
            primaryjoin=lambda: and_(
                cls.id == foreign(Comment.owner_id),
                Comment.owner_type == commentable_type_of(cls),
            ),
            viewonly=True,
            lazy="raise_on_sql",
            order_by=lambda: (Comment.commented_at.desc(), Comment.id.desc()),
        )


__all__ = ["HasCommentsMixin", "commentable_type_of"]
