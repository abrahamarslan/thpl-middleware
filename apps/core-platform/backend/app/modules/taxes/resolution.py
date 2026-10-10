"""Taxes as a resolution facet — "which tax applies to this line?".

Registers into the platform resolution engine (``app.modules.resolution``):

  * ``TaxFacet`` — candidates are ``tax.tax_assignments``; a context (inter/intra ×
    sales/purchase) narrows one owner's rows with :func:`select_applicable` (unchanged:
    the most specific context level wins, several taxes at that level apply together in
    ``position`` order); the organization default is ``org_default_tax_preferences``.
  * the accountant-approved default policies (2026-10-08) for sales and purchase lines:

        line → contact (exemption only) → item → item's categories → contact (taxes only) → organization default

    A customer's exemption (SEZ, overseas, an exempt body) overrides the item's tax — Zoho's
    own precedence; the contact's default tax only answers when neither the item nor its
    categories carry one. Configurable per tenant / organization through
    ``/api/resolution/policies/tax/{subject}``.

Usability (fail-closed): an assignment whose tax was soft-deleted or made inactive does not
silently fall through to the next owner — the step returns ``unusable``.

``filters``: ``exemption_only`` keeps exemption assignments, ``taxes_only`` keeps tax
assignments — how one owner (the contact) can sit at two places in a chain.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.resolution import Expansion, OwnerRef, Policy, Step, Subject, resolution_registry
from app.modules.resolution.facet import Facet
from app.modules.taxes.assignment import TaxAssignment
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.enums import TaxSpecification, TaxTransactionType
from app.modules.taxes.preference import OrgDefaultTaxPreference


class TaxContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: TaxSpecification | None = None      # inter / intra (derived by the caller from place of supply)
    transaction_type: TaxTransactionType | None = None  # sales / purchase


def select_applicable(rows: Sequence[Any], *, specification: str | None, transaction_type: str | None) -> list[Any]:
    # Imported lazily: assignment_service imports this module for the wrapper.
    from app.modules.taxes.assignment_service import select_applicable as _select

    return _select(rows, specification=specification, transaction_type=transaction_type)


def _component_unusable(component: TaxComponent | None) -> str | None:
    if component is None:
        return "tax_deleted"
    if component.deleted_at is not None:
        return "tax_deleted"
    if component.is_inactive or component.status not in (None, "active") or component.deactivation_date is not None:
        return "tax_inactive"
    return None


class _TaxData:
    def __init__(self, rows: list[TaxAssignment], defaults: list[OrgDefaultTaxPreference]) -> None:
        self._by_owner: dict[OwnerRef, list[TaxAssignment]] = defaultdict(list)
        for row in rows:
            self._by_owner[OwnerRef(row.owner_type_code, row.owner_id)].append(row)
        self._defaults = defaults

    def candidates(self, owner: OwnerRef) -> list[TaxAssignment]:
        return self._by_owner.get(owner, [])

    def has_pending(self, owner: OwnerRef) -> bool:
        return any(row.is_pending for row in self._by_owner.get(owner, []))

    def organization_default(self, organization_id: int | None, context: TaxContext) -> list[TaxComponent]:
        if context.specification is None:
            return []
        spec = context.specification.value
        mine = [d for d in self._defaults if d.tax_specification == spec and d.organization_id == organization_id
                and organization_id is not None]
        shared = [d for d in self._defaults if d.tax_specification == spec and d.organization_id is None]
        for preference in mine or shared:
            if preference.default_tax is not None:
                return [preference.default_tax]
        return []

    def unusable(self, candidate: Any, organization_id: int | None) -> str | None:
        if isinstance(candidate, TaxComponent):
            return _component_unusable(candidate)
        if candidate.tax_component_id is not None:
            return _component_unusable(candidate.tax_component)
        if candidate.tax_exemption_id is not None:
            exemption = candidate.tax_exemption
            if exemption is None or exemption.deleted_at is not None:
                return "exemption_deleted"
        return None


class TaxFacet(Facet):
    code = "tax"
    context_model = TaxContext
    description = "Which taxes (or exemption) apply — tax.tax_assignments + org_default_tax_preferences."
    filters = {
        "exemption_only": lambda a: getattr(a, "tax_exemption_id", None) is not None,
        "taxes_only": lambda a: getattr(a, "tax_component_id", None) is not None,
    }

    async def load(self, db: AsyncSession, owners: Collection[OwnerRef], subjects: Sequence[Subject]) -> _TaxData:
        rows: list[TaxAssignment] = []
        if owners:
            # include_deleted reaches the joined tax: a soft-deleted tax must be SEEN (unusable), not hidden
            # (which would read as "no candidates" and fall through). Live assignments only, filtered by hand.
            rows = list((await db.scalars(
                select(TaxAssignment)
                .where(tuple_(TaxAssignment.owner_type_code, TaxAssignment.owner_id).in_(sorted(owners)),
                       TaxAssignment.deleted_at.is_(None))
                .options(joinedload(TaxAssignment.tax_component), joinedload(TaxAssignment.tax_exemption))
                .order_by(TaxAssignment.position, TaxAssignment.id)
                .execution_options(include_deleted=True)
            )).unique().all())
        specs = {s.context.specification.value for s in subjects if s.context.specification is not None}
        defaults: list[OrgDefaultTaxPreference] = []
        if specs:
            orgs = {s.organization_id for s in subjects if s.organization_id is not None}
            scope = OrgDefaultTaxPreference.organization_id.is_(None)
            if orgs:
                scope = or_(scope, OrgDefaultTaxPreference.organization_id.in_(orgs))
            defaults = list((await db.scalars(
                select(OrgDefaultTaxPreference)
                .where(OrgDefaultTaxPreference.tax_specification.in_(specs), scope)
                .options(joinedload(OrgDefaultTaxPreference.default_tax))
            )).unique().all())
        return _TaxData(rows, defaults)

    def select(self, candidates: Sequence[Any], context: TaxContext) -> list[Any]:
        live = [c for c in candidates if not c.is_pending]
        return select_applicable(
            live,
            specification=context.specification.value if context.specification else None,
            transaction_type=context.transaction_type.value if context.transaction_type else None,
        )

    def describe(self, value: Any) -> dict[str, Any]:
        if isinstance(value, TaxComponent):
            return {"kind": "tax", "tax_component_id": value.id, "tax_name": value.tax_name,
                    "tax_percentage": str(value.tax_percentage), "source": "organization_default"}
        if value.tax_exemption_id is not None:
            exemption = value.tax_exemption
            return {"kind": "exemption", "assignment_id": value.id, "tax_exemption_id": value.tax_exemption_id,
                    "tax_exemption_code": getattr(exemption, "tax_exemption_code", None)}
        component = value.tax_component
        return {"kind": "tax", "assignment_id": value.id, "tax_component_id": value.tax_component_id,
                "tax_name": getattr(component, "tax_name", None),
                "tax_percentage": str(component.tax_percentage) if component is not None else None,
                "tax_specification": value.tax_specification, "transaction_type": value.transaction_type,
                "position": value.position}


TAX_FACET = resolution_registry.register_facet(TaxFacet())

#: Roles a document line can name, and the item → categories expansion (``categories`` expander).
_LINE_ROLES = frozenset({"line", "item", "contact"})
_LINE_EXPANSIONS = (Expansion(role="item_category", from_role="item", expander="categories"),)
_LINE_STEPS = (
    Step("line"),
    Step("contact", filter="exemption_only"),
    Step("item"),
    Step("item_category"),
    Step("contact", filter="taxes_only"),
)

for _subject, _what in (("sales_line", "a sales document line"), ("purchase_line", "a purchase document line")):
    resolution_registry.register_policy(Policy(
        facet="tax", subject=_subject, roles=_LINE_ROLES, expansions=_LINE_EXPANSIONS, steps=_LINE_STEPS,
        description=f"Taxes of {_what}: explicit line tax → the contact's exemption → the item → the item's "
                    "categories → the contact's default tax → the organization default (accountant-approved "
                    "2026-10-08).",
    ))

__all__ = ["TAX_FACET", "TaxContext", "TaxFacet"]
