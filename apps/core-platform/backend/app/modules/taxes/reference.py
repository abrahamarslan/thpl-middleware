"""Reference / lookup layer.

``GstTreatmentType`` is Zoho's fixed GST / tax treatment vocabulary
(business_gst, consumer, overseas, …). It collapses the identical
``gst_treatments`` and ``tax_treatments`` payload shapes — same keys under two
names — into ONE table, deduped on ``value``.

GLOBAL reference data (allow-listed in ``tests/test_tenancy.py``): the
vocabulary is CBIC-defined and identical across organizations, so the table
carries no ``tenant_id`` / ``organization_id``. Provenance of the last
confirming source is polymorphic (``owner_type`` / ``owner_id``, e.g.
``connection`` + the connection id). Both are NULLABLE here — NULL = unscoped —
so this table declares the pair itself instead of using
``PolymorphicOwnerMixin``, whose columns are NOT NULL.

There is no Zoho adapter yet: the ``gst_treatments`` / ``tax_treatments``
endpoints are not in ``docs/zoho-docs-md``, so none is registered
(``mappings.py`` records the captured shape for when one is).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    HashGuardMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.taxes.enums import TAX_SCHEMA, GstTreatmentCategory, TaxOwnerType, values

_LIVE = text("deleted_at IS NULL")


class GstTreatmentType(
    BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, HashGuardMixin,
    SoftDeleteFilteredMixin, Base,
):
    """One row per GST / tax treatment vocabulary entry."""

    __tablename__ = "gst_treatment_types"
    __table_args__ = (
        CheckConstraint(f"category IS NULL OR category IN ({values(GstTreatmentCategory)})",
                        name="chk_gst_treatment_types_category"),
        CheckConstraint(f"owner_type IS NULL OR owner_type IN ({values(TaxOwnerType)})",
                        name="chk_gst_treatment_types_owner_type"),
        Index("uq_gst_treatment_types_value", "value", unique=True, postgresql_where=_LIVE),
        Index("uq_gst_treatment_types_code", "code", unique=True, postgresql_where=_LIVE),
        Index("ix_gst_treatment_types_owner", "owner_type", "owner_id"),
        {"schema": TAX_SCHEMA, "comment": "GST / tax treatment vocabulary (global reference data)."},
    )

    owner_type: Mapped[str | None] = mapped_column(
        Text, comment="Polymorphic owner class: 'connection' / 'organization' / 'system'; NULL = unscoped",
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Polymorphic owner id (resolve with owner_type); no FK",
    )

    code: Mapped[int] = mapped_column(Integer, nullable=False, comment="Source's small ordinal treatment code")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="Natural key, e.g. 'business_gst'")
    label: Mapped[str | None] = mapped_column(Text, comment="Source label")
    value_formatted: Mapped[str | None] = mapped_column(Text, comment="Formatted display value from source")
    description: Mapped[str | None] = mapped_column(Text, comment="Human-readable description of the treatment")
    category: Mapped[str | None] = mapped_column(Text, comment="'business' or 'consumer'")
    allowed_for_sales: Mapped[bool | None] = mapped_column(
        Boolean, comment="NULL = unknown, treated conservatively by consumers",
    )
    allowed_for_purchase: Mapped[bool | None] = mapped_column(
        Boolean, comment="NULL = unknown, treated conservatively",
    )

    def __repr__(self) -> str:
        return f"<GstTreatmentType id={self.id} value={self.value!r} code={self.code}>"


__all__ = ["GstTreatmentType"]
