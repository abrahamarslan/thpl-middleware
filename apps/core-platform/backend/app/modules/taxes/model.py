"""``tax`` schema — the single import surface for the module's tables.

    component.py   TaxComponent (tax | compound_tax | tax_group) · TaxGroupMember
    exemption.py   TaxExemption
    org_tax.py     OrganizationTaxComponent      organization ↔ component, M:N
    preference.py  OrgDefaultTaxPreference       default component per organization + inter/intra
    reference.py   GstTreatmentType              global reference vocabulary
    tax_registration.py  TaxRegistration        GSTIN / PAN / Udyam … of any owner (polymorphic)
    assignment.py  TaxableEntityType (global policy) · TaxAssignment (polymorphic owner → tax)

Importing this module registers every table with ``Base.metadata`` — that is
what ``alembic/env.py`` and the registry rely on, so import from here rather
than from the individual files when only registration matters.
"""

from app.modules.taxes.assignment import TaxableEntityType, TaxAssignment
from app.modules.taxes.component import TaxComponent, TaxGroupMember
from app.modules.taxes.enums import TAX_SCHEMA
from app.modules.taxes.exemption import TaxExemption
from app.modules.taxes.org_tax import OrganizationTaxComponent
from app.modules.taxes.preference import OrgDefaultTaxPreference
from app.modules.taxes.reference import GstTreatmentType
from app.modules.taxes.tax_registration import TaxRegistration

__all__ = [
    "TAX_SCHEMA",
    "GstTreatmentType",
    "OrgDefaultTaxPreference",
    "OrganizationTaxComponent",
    "TaxAssignment",
    "TaxComponent",
    "TaxExemption",
    "TaxGroupMember",
    "TaxRegistration",
    "TaxableEntityType",
]
