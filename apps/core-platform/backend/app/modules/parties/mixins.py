"""HasCustomerMixin / HasVendorMixin / HasPartyMixin — point a document at a party, one line.

    class Invoice(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasCustomerMixin, Base):
        __table_args__ = (HasCustomerMixin.customer_fk("invoices"), ...)

    class Bill(..., HasVendorMixin, Base):            # vendor_id
    class CustomerPayment(..., HasCustomerMixin, Base)
    class Estimate / SalesOrder / CreditNote (..., HasCustomerMixin, Base)

What each mixin gives (``<role>`` = customer | vendor | party):

* ``<role>_id``  — BIGINT, NOT NULL by default (a document always has its party), indexed by the
  model's own indexes;
* ``<role>``     — a ``viewonly``, ``lazy="raise"`` relationship to ``Party`` (load with ``joinedload``);
* ``<role>_fk(table)`` — the composite ``(tenant_id, organization_id, <role>_id)`` FK to
  ``party.parties`` — a document can never name another organization's party;
* ``zoho_<role>_reference()`` — the engine ``ReferenceRule`` that turns the Zoho payload's
  ``customer_id`` / ``vendor_id`` into the local FK through the crosswalk (module ``parties``, DEFER:
  a document synced before its party waits on ``sync.pending_references`` and the reconcile lane links
  it). Merged-away Zoho contact ids resolve to the survivor (crosswalk ``link_state='merged'``).

Why a role-named column rather than one ``party_id`` everywhere: an invoice's party IS its customer,
and the name says which role the document needs. The role is enforced by the owning service for local
writes (``assert_role``); not by a CHECK, because Zoho is trusted for its own documents.

Persons on documents (Zoho ``contact_persons[]`` on an invoice: who receives it) and the address the
document was issued to (a FROZEN ``geo.place_links`` snapshot) are the document module's own links —
deliberately not part of this mixin.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKeyConstraint
from sqlalchemy.orm import declared_attr, foreign, mapped_column, relationship

from app.common.exception.errors import AppError
from app.modules.parties.enums import PARTIES_MODULE, PARTY_SCHEMA, PartyType


class PartyRoleError(AppError):
    status_code = 422
    code = "party_role_mismatch"


def _party_reference(role: str, *, required: bool = True) -> type:
    column = f"{role}_id"

    def fk(table: str) -> ForeignKeyConstraint:
        return ForeignKeyConstraint(
            ["tenant_id", "organization_id", column],
            [f"{PARTY_SCHEMA}.parties.tenant_id", f"{PARTY_SCHEMA}.parties.organization_id",
             f"{PARTY_SCHEMA}.parties.id"],
            name=f"fk_{table}_{role}", ondelete="RESTRICT",
        )

    def zoho_reference(attr: str | None = None) -> Any:
        from app.modules.sync.contract import OnMissing, ReferenceRule

        return ReferenceRule(attr=attr or column, module=PARTIES_MODULE, fk=column, on_missing=OnMissing.DEFER)

    def _column(cls):  # noqa: ANN001, ARG001
        return mapped_column(BigInteger, nullable=not required,
                             comment=f"party.parties ({role}); same organization (composite FK)")

    def _relationship(cls):  # noqa: ANN001
        from app.modules.parties.model import Party

        return relationship(
            Party, primaryjoin=lambda: foreign(getattr(cls, column)) == Party.id, viewonly=True, lazy="raise",
        )

    attrs: dict[str, Any] = {
        "__doc__": f"``{column}`` → party.parties (role {role}).",
        column: declared_attr(_column),
        role: declared_attr(_relationship),
        f"{role}_fk": staticmethod(fk),
        f"zoho_{role}_reference": staticmethod(zoho_reference),
    }
    return type(f"Has{role.title()}Mixin", (), attrs)


#: Sales documents and customer payments: ``customer_id``.
HasCustomerMixin = _party_reference(PartyType.CUSTOMER.value)
#: Purchase documents and vendor payments: ``vendor_id``.
HasVendorMixin = _party_reference(PartyType.VENDOR.value)
#: Role-neutral (journals, statements, any-party links): ``party_id``.
HasPartyMixin = _party_reference("party")


def assert_role(party: Any, role: str) -> None:
    """Refuse a LOCAL write that hangs a customer document on a vendor (or the reverse)."""
    if role in (PartyType.CUSTOMER.value, PartyType.VENDOR.value) and party.party_type != role:
        raise PartyRoleError(f"{party.name!r} is a {party.party_type}, not a {role}",
                             data={"party_type": party.party_type, "required": role})


__all__ = ["HasCustomerMixin", "HasPartyMixin", "HasVendorMixin", "PartyRoleError", "assert_role"]
