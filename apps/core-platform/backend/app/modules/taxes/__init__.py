"""Taxes — the ``tax`` schema (canonical masters, package-by-feature).

    enums.py  model.py                      vocabularies; single import surface for the tables
    component.py    TaxComponent (tax | compound_tax | tax_group) · TaxGroupMember
    exemption.py    TaxExemption           org-defined exemption reasons (P2 fields)
    org_tax.py      OrganizationTaxComponent   organization ↔ component grants (M:N)
    preference.py   OrgDefaultTaxPreference    default component per organization + inter/intra
    reference.py    GstTreatmentType       global treatment vocabulary
    mappings.py     lineage catalog of every Zoho leaf path (tests keep it honest)
    schema.py crud.py service.py api.py     the read side
    zoho/           the Zoho adapter: taxes · tax_groups (disabled) · tax_exemptions

HTTP: /api/taxes. Docs: docs/zoho-sync-implementation/adapters/taxes.md
"""
