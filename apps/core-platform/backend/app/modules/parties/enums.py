"""Vocabularies of the ``party`` schema (CHECKs are built FROM these, so they cannot drift).

A **party** is a commercial counterparty — a customer or a vendor (Zoho calls both a *contact*:
``/contacts``, ``contact_type``). One table holds both roles: they share almost everything (names,
persons, addresses, tax registrations, terms, currency), and Zoho lets the same shape be either. The
role-specific differences are columns that are simply NULL for the other role, plus role-aware
validation of LOCAL writes; Zoho's rows are trusted as sent (no role CHECKs — Zoho returns
``customer_sub_type`` on vendors too). When the roles diverge further, a 1:1 role profile table
(``party.customer_profiles`` / ``vendor_profiles``) is the extension point, not a second party table.

CHECKs exist only for Zoho's DOCUMENTED closed sets. Observed-but-undocumented values (e.g.
``gst_treatment = business_registered_composition``, ``payment_terms = -3``) must never fail a sync.
"""

from __future__ import annotations

import enum

from app.modules.entities.enums import values

#: Postgres schema of the commercial parties.
PARTY_SCHEMA = "party"

#: Crosswalk module keys (``sync.sync_records.module``); the Zoho endpoint is ``/contacts``.
PARTIES_MODULE = "parties"
CONTACT_PERSONS_MODULE = "contact_persons"

#: ``core.entity_types`` codes (also the owner type of addresses, media, documents, comments, taxes …).
PARTY_ENTITY_TYPE = "party"
CONTACT_PERSON_ENTITY_TYPE = "contact_person"


class PartyType(enum.StrEnum):
    """Zoho ``contact_type`` (documented closed set)."""

    CUSTOMER = "customer"
    VENDOR = "vendor"


class CustomerSubType(enum.StrEnum):
    """Zoho ``customer_sub_type`` (documented closed set)."""

    BUSINESS = "business"
    INDIVIDUAL = "individual"


class PartyStatus(enum.StrEnum):
    """Zoho ``status``."""

    ACTIVE = "active"
    INACTIVE = "inactive"


__all__ = [
    "CONTACT_PERSONS_MODULE",
    "CONTACT_PERSON_ENTITY_TYPE",
    "CustomerSubType",
    "PARTIES_MODULE",
    "PARTY_ENTITY_TYPE",
    "PARTY_SCHEMA",
    "PartyStatus",
    "PartyType",
    "values",
]
