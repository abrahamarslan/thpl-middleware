"""HasAccountsMixin — let any model carry account assignments with one line of inheritance.

    class Item(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasTaxesMixin, HasAccountsMixin, Base): ...

Read path: ``selectinload(Model.account_assignments).joinedload(AccountAssignment.account)``
loads every live assignment for a result set in ONE extra query; ``lazy="raise_on_sql"``
is the N+1 firewall (``HasTaxesMixin`` / ``HasCommentsMixin`` do the same).

Write path: strictly through ``accounting.assignment_service`` (or
``PUT /api/accounting/assignments/{owner_type}/{owner_id}``) — the relationship is
``viewonly`` because every write needs the policy, purpose and scope checks the service
owns, and mutating a polymorphic relationship under ``AsyncSession`` crashes with
``MissingGreenlet``.

"Which account applies?" is NOT read off this relationship: an owner that carries nothing
falls back to its organization, and a document line asks a whole chain. That is the
resolution engine's job (``app.modules.resolution``, facet ``account``).

The owner's class is its ``core.entity_types`` code — the snake_case class name unless the
model sets ``__account_owner_type__``. Opting a class in is a migration concern:
``accounting.registration.register_account_owner_type``.
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.accounting.assignment import AccountAssignment

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def account_owner_type_of(model: type) -> str:
    """The ``core.entity_types.code`` a model's account assignments are stored under."""
    explicit = getattr(model, "__account_owner_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasAccountsMixin:
    @declared_attr
    def account_assignments(cls):  # noqa: N805
        return relationship(
            AccountAssignment,
            primaryjoin=lambda: and_(
                cls.id == foreign(AccountAssignment.owner_id),
                AccountAssignment.owner_type_code == account_owner_type_of(cls),
            ),
            viewonly=True,
            lazy="raise_on_sql",
            order_by=lambda: (AccountAssignment.purpose_code.asc(), AccountAssignment.id.asc()),
        )


__all__ = ["HasAccountsMixin", "account_owner_type_of"]
