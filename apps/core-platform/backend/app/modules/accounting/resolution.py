"""Accounts as a resolution facet — "which ledger account does this post to?".

Registers into the platform resolution engine (``app.modules.resolution``):

  * ``AccountFacet`` — candidates are ``accounting.account_assignments`` for the context's
    PURPOSE; within one owner the exact currency beats the any-currency row; the
    organization default is the organization's own assignment for the purpose
    (owner ``("organization", id)``).
  * the accountant-approved default policies (2026-10-08). The purpose comes from the
    context, so one policy serves every purpose of a subject kind:

        sales_line / purchase_line   line → item → item's categories → contact → organization
        inventory                    item → item's categories → organization
        document_party               contact → organization          (receivable / payable)
        tax_line                     tax_component → organization    (output / input tax, TDS)

    "The item's income account beats the contact's" is the order above. Configurable per
    tenant / organization: ``/api/resolution/policies/account/{subject}``.

Usability (fail-closed): an assignment pointing at an inactive or soft-deleted account
returns ``unusable`` — falling through to the organization default would post to the
wrong account without anyone noticing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.accounting.assignment import AccountAssignment
from app.modules.accounting.enums import AccountStatus
from app.modules.resolution import Expansion, OwnerRef, Policy, Step, Subject, resolution_registry
from app.modules.resolution.facet import Facet

ORGANIZATION_TYPE = "organization"


class AccountContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(..., min_length=1, max_length=48, description="accounting.account_purposes.code")
    currency_id: int | None = Field(None, description="Document currency; NULL = base / any")


class _AccountData:
    def __init__(self, rows: list[AccountAssignment]) -> None:
        self._by_owner: dict[OwnerRef, list[AccountAssignment]] = defaultdict(list)
        for row in rows:
            self._by_owner[OwnerRef(row.owner_type_code, row.owner_id)].append(row)

    def candidates(self, owner: OwnerRef) -> list[AccountAssignment]:
        return self._by_owner.get(owner, [])

    def has_pending(self, owner: OwnerRef) -> bool:
        return any(row.is_pending for row in self._by_owner.get(owner, []))

    def organization_default(self, organization_id: int | None, context: AccountContext) -> list[AccountAssignment]:
        if organization_id is None:
            return []
        rows = self._by_owner.get(OwnerRef(ORGANIZATION_TYPE, organization_id), [])
        return pick(rows, context)

    def unusable(self, candidate: AccountAssignment, organization_id: int | None) -> str | None:
        account = candidate.account
        if account is None or account.deleted_at is not None:
            return "account_deleted"
        if account.status != AccountStatus.ACTIVE.value:
            return "account_inactive"
        return None


def pick(rows: Sequence[AccountAssignment], context: AccountContext) -> list[AccountAssignment]:
    """One owner's answer for a purpose: the exact currency, else the any-currency row."""
    live = [r for r in rows if r.purpose_code == context.purpose and r.account_id is not None]
    exact = [r for r in live if context.currency_id is not None and r.currency_id == context.currency_id]
    if exact:
        return exact[:1]
    general = [r for r in live if r.currency_id is None]
    return general[:1]


class AccountFacet(Facet):
    code = "account"
    context_model = AccountContext
    description = "Which ledger account applies for a purpose — accounting.account_assignments."

    async def load(self, db: AsyncSession, owners: Collection[OwnerRef], subjects: Sequence[Subject]) -> _AccountData:
        everyone = set(owners) | {OwnerRef(ORGANIZATION_TYPE, s.organization_id)
                                  for s in subjects if s.organization_id is not None}
        purposes = {s.context.purpose for s in subjects}
        if not everyone or not purposes:
            return _AccountData([])
        # include_deleted reaches the joined account: a soft-deleted account must be SEEN (unusable),
        # never hidden (which would read as "no candidates" and fall through). Live assignments only.
        rows = list((await db.scalars(
            select(AccountAssignment)
            .where(tuple_(AccountAssignment.owner_type_code, AccountAssignment.owner_id).in_(sorted(everyone)),
                   AccountAssignment.purpose_code.in_(sorted(purposes)),
                   AccountAssignment.deleted_at.is_(None))
            .options(joinedload(AccountAssignment.account))
            .order_by(AccountAssignment.id)
            .execution_options(include_deleted=True)
        )).unique().all())
        return _AccountData(rows)

    def select(self, candidates: Sequence[Any], context: AccountContext) -> list[Any]:
        return pick(candidates, context)

    def describe(self, value: AccountAssignment) -> dict[str, Any]:
        account = value.account
        return {"assignment_id": value.id, "purpose": value.purpose_code, "account_id": value.account_id,
                "account_uuid": str(account.uuid) if account is not None else None,
                "display_name": account.display_name if account is not None else None,
                "account_type": account.account_type if account is not None else None,
                "currency_id": value.currency_id, "source_system": value.source_system}


ACCOUNT_FACET = resolution_registry.register_facet(AccountFacet())

_ITEM_CATEGORIES = (Expansion(role="item_category", from_role="item", expander="categories"),)

_POLICIES = (
    Policy(facet="account", subject="sales_line", roles=frozenset({"line", "item", "contact"}),
           expansions=_ITEM_CATEGORIES,
           steps=(Step("line"), Step("item"), Step("item_category"), Step("contact")),
           description="Income account of a sales line: line → item → item's categories → contact → "
                       "organization (accountant-approved 2026-10-08)."),
    Policy(facet="account", subject="purchase_line", roles=frozenset({"line", "item", "contact"}),
           expansions=_ITEM_CATEGORIES,
           steps=(Step("line"), Step("item"), Step("item_category"), Step("contact")),
           description="Expense / COGS account of a purchase line: line → item → item's categories → vendor → "
                       "organization."),
    Policy(facet="account", subject="inventory", roles=frozenset({"item"}), expansions=_ITEM_CATEGORIES,
           steps=(Step("item"), Step("item_category")),
           description="Inventory account of an item: item → its categories → organization."),
    Policy(facet="account", subject="document_party", roles=frozenset({"contact"}),
           steps=(Step("contact"),),
           description="Control account of a document's party (receivable / payable, advances): contact → "
                       "organization."),
    Policy(facet="account", subject="tax_line", roles=frozenset({"tax_component"}),
           steps=(Step("tax_component"),),
           description="Ledger account a tax posts to (output / input tax, TDS payable): tax → organization."),
)
for _policy in _POLICIES:
    resolution_registry.register_policy(_policy)

__all__ = ["ACCOUNT_FACET", "AccountContext", "AccountFacet", "pick"]
