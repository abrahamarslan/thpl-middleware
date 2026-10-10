"""HasCurrencyMixin — a currency on any organization-scoped model, one line.

    class Party(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasCurrencyMixin, Base):
        __table_args__ = (HasCurrencyMixin.currency_fk("parties"), ...)

What it gives:

* ``currency_id`` — ``currency.currencies.id``; NULL means "the organization's base currency"
  (what Zoho says with ``currency_id: ""``);
* ``currency`` — a ``viewonly``, ``lazy="raise"`` relationship (load it with ``joinedload``);
* ``currency_fk(table)`` — the composite ``(tenant_id, currency_id)`` FK, so a row can never point at
  another tenant's currency. A mixin cannot contribute to ``__table_args__`` without fighting the
  model's own tuple, so the model includes this constraint explicitly.

For Zoho modules the reference is resolved by the engine, not here:
``ReferenceRule(attr="currency_id", module="currencies", fk="currency_id", on_missing=OnMissing.DEFER)``.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, declared_attr, foreign, mapped_column, relationship

from app.modules.currencies.model import Currency


class HasCurrencyMixin:
    currency_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="currency.currencies; NULL = the organization's base currency",
    )

    @declared_attr
    def currency(cls):  # noqa: N805
        return relationship(
            Currency, primaryjoin=lambda: foreign(cls.currency_id) == Currency.id, viewonly=True, lazy="raise",
        )

    @staticmethod
    def currency_fk(table: str) -> ForeignKeyConstraint:
        """The composite same-tenant FK — put it in the model's ``__table_args__``."""
        return ForeignKeyConstraint(
            ["tenant_id", "currency_id"], ["currency.currencies.tenant_id", "currency.currencies.id"],
            name=f"fk_{table}_currency", ondelete="RESTRICT",
        )


__all__ = ["HasCurrencyMixin"]
