"""Tax exemption reasons.

``TaxExemption`` mirrors Zoho's ``tax_exemptions`` list, scoped to a tenant with
an optional owning organization (``TenantScopedMixin``: NULL = tenant-wide).

**Privacy finding — read before touching this table.** The observed source data
mixes genuine tax categories ("BILL OF SUPPLY", "0% TAX") with what read as
individual customers' personal names used as ad-hoc per-customer labels
(e.g. "MINABEN PATEL"). Consequences:

  * ``tax_exemption_code`` and ``exemption_name`` are classified **P2**: the
    erasure job must anonymize matching rows on a DPDP request. Matching is
    free-text today, not a foreign key.
  * ``type`` and ``exemption_type`` are OPEN vocabularies (AP8) — only ``item``
    and ``exempt`` were observed but Zoho defines them, so they carry no CHECK
    and an unknown value is stored rather than halting the page.

The ``*_formatted`` columns are raw source echoes kept for sync fidelity. The
trigram index that feeds the near-duplicate review queue (AP25) is a raw-SQL
concern and lives with the migration, not the ORM.

No source id column: identity is the crosswalk's (``sync.sync_records``).
"""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    HashGuardMixin,
    TenantScopedMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.enums import TAX_SCHEMA


class TaxExemption(
    BigIntPKWithUUIDv7Mixin, TenantScopedMixin, AuditMixin, AppMetaMixin, TimestampMixin,
    HashGuardMixin, SoftDeleteFilteredMixin, Base,
):
    """An exemption reason used as a line-item flag."""

    __tablename__ = "tax_exemptions"
    __table_args__ = (
        {"schema": TAX_SCHEMA, "comment": "Tax exemption reasons (P2: codes/names may hold personal names)."},
    )

    tax_exemption_code: Mapped[str | None] = mapped_column(
        Text,
        comment="P2 -- observed to contain individual persons' names used as ad-hoc per-customer labels "
                "rather than a category code; the erasure job must anonymize matching rows "
                "(manual/free-text matching, R15 decision 4)",
    )
    description: Mapped[str | None] = mapped_column(Text, comment="Free-text description")
    type: Mapped[str | None] = mapped_column(
        Text,
        comment="Open text, no CHECK (AP8): only 'item' observed, vocabulary assumed source-defined "
                "and possibly larger than sampled",
    )
    type_formatted: Mapped[str | None] = mapped_column(Text, comment="Formatted echo of `type`")
    exemption_name: Mapped[str | None] = mapped_column(
        Text,
        comment="P2 -- same contamination risk as tax_exemption_code; always empty in observed "
                "samples but not schema-guaranteed to stay that way",
    )
    exemption_type: Mapped[str | None] = mapped_column(
        Text, comment="Open text, no CHECK (AP8): only 'exempt' observed",
    )
    exemption_type_formatted: Mapped[str | None] = mapped_column(
        Text, comment="Formatted echo of `exemption_type`",
    )

    def __repr__(self) -> str:
        return f"<TaxExemption id={self.id} code={self.tax_exemption_code!r}>"


__all__ = ["TaxExemption"]
