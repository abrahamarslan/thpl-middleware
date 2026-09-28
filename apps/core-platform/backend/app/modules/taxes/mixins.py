"""HasTaxesMixin — let any model carry taxes with one line of inheritance.

    class Item(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasTaxesMixin, Base): ...

Read path: ``selectinload(Model.tax_assignments)`` eager-loads every live
assignment for a result set in ONE extra query (no N+1); chain
``.joinedload(TaxAssignment.tax_component)`` to bring the tax itself.
``lazy="raise_on_sql"`` is the N+1 firewall: touching the attribute without the
explicit eager load raises instead of silently issuing SQL under ``AsyncSession``.

Write path: strictly through ``taxes.assignment_service`` (or
``PUT /api/taxes/assignments/{owner_type}/{owner_id}``) — the relationship is
``viewonly`` because mutating it triggers implicit lazy loads that crash async
SQLAlchemy with ``MissingGreenlet``, and because every write needs the policy,
grant and scope checks the service owns.

The owner's class is its ``core.entity_types`` code, derived from the class name
(``InvoiceLine`` → ``invoice_line``) unless the model sets ``__taxable_type__``.
Making the class taxable also needs its registry + policy rows — see
``taxes/registration.py`` — which is a migration concern, not a model one.
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.taxes.assignment import TaxAssignment

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def taxable_type_of(model: type) -> str:
    """The ``core.entity_types.code`` a model's assignments are stored under."""
    explicit = getattr(model, "__taxable_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasTaxesMixin:
    @declared_attr
    def tax_assignments(cls):  # noqa: N805
        return relationship(
            TaxAssignment,
            primaryjoin=lambda: and_(
                cls.id == foreign(TaxAssignment.owner_id),
                TaxAssignment.owner_type_code == taxable_type_of(cls),
            ),
            viewonly=True,
            lazy="raise_on_sql",
            order_by=lambda: (TaxAssignment.position.asc(), TaxAssignment.id.asc()),
        )


__all__ = ["HasTaxesMixin", "taxable_type_of"]
