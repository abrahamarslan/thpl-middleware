"""Vocabularies for the ``tax`` schema.

Every closed set below is stored in a ``text`` column guarded by a CHECK built
FROM the enum (``values()``), so the constraint and the vocabulary cannot
drift apart. Vocabularies Zoho may extend without notice deliberately have NO
CHECK — ``tax_specific_type`` (India, Mexico and South Africa each define their
own), ``tax_exemptions.type`` / ``exemption_type``, ``tax_components.status``:
an unknown upstream value must be stored, not halt a page (AP8).
"""

from __future__ import annotations

import enum

#: Postgres schema holding every tax table.
TAX_SCHEMA = "tax"


def values(enum_cls: type[enum.Enum]) -> str:
    """``"'a','b'"`` — for building a CHECK constraint from an enum."""
    return ",".join(f"'{member.value}'" for member in enum_cls)


class TaxType(enum.StrEnum):
    """Discriminator shared by Zoho's ``tax`` and ``tax_group`` entities.

    Zoho uses one id namespace across both shapes, which is why both live in a
    single table (``tax.tax_components``); this value decides whether the row is
    a leaf or a composite that owns ``tax_group_members`` rows.
    """

    TAX = "tax"                        # a single component, e.g. CGST9
    COMPOUND_TAX = "compound_tax"      # a leaf levied on top of other taxes
    TAX_GROUP = "tax_group"            # a composite, e.g. GST18 (see members)


class TaxSpecificType(enum.StrEnum):
    """The specific GST leg a component represents (Zoho ``tax_specific_type``).

    Documentation of the India legs, not a CHECK: Zoho also defines Mexican
    (isr/iva/ieps) and South African (soa_*, ciu_*, export_of_shg) values. Zoho's
    generic sentinel ``"tax"`` and the empty string are normalised to NULL by
    the ``specific_type`` codec, and a ``tax_group`` row is always NULL
    (``chk_tax_components_group_no_specific_type``), so neither is stored.
    """

    CGST = "cgst"                      # Central GST
    SGST = "sgst"                      # State GST
    IGST = "igst"                      # Integrated GST
    UTGST = "utgst"                    # Union Territory GST
    CESS = "cess"                      # Compensation cess
    NIL = "nil"                        # nil-rated — documented by Zoho (India)


class TaxOwnerType(enum.StrEnum):
    """Polymorphic owner classes for global-reference provenance."""

    CONNECTION = "connection"          # the Zoho connection that confirmed the row
    ORGANIZATION = "organization"      # org_management.organizations.id
    SYSTEM = "system"                  # platform-authored


class TaxSpecification(enum.StrEnum):
    """Inter-state vs intra-state context a tax or a default applies to."""

    INTER = "inter"                    # inter-state (typically IGST)
    INTRA = "intra"                    # intra-state (typically CGST + SGST)


class GstTreatmentCategory(enum.StrEnum):
    """Broad bucket of a GST treatment."""

    BUSINESS = "business"
    CONSUMER = "consumer"


__all__ = [
    "TAX_SCHEMA",
    "GstTreatmentCategory",
    "TaxOwnerType",
    "TaxSpecificType",
    "TaxSpecification",
    "TaxType",
    "values",
]
