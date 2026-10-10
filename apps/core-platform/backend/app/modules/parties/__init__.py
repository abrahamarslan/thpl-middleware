"""Parties — customers and vendors (Zoho "contacts") and their contact persons, organization-scoped.

    party.parties          ENTITY  one customer or vendor of one organization (Zoho crosswalk ``parties``)
    party.contact_persons  ENTITY  people of a party (Zoho crosswalk ``contact_persons``)
    party.payment_terms    ENTITY  payment terms as Zoho names them (learned)
    tax.tax_registrations  ENTITY  GSTIN / PAN / Udyam … (taxes module; owner ``party``)

Addresses live in the location hub (geo.place_links → geo.places), custom fields in extfields, the
sub-category in categories (taxonomy ``customer_sub_category``), media / documents / comments in their
modules. Documents that name a party (invoices, estimates, payments) use ``mixins.HasCustomerMixin`` /
``HasVendorMixin``. Zoho adapter: ``zoho/``. Docs: docs/implementation-plan/contacts-module.md.
"""
