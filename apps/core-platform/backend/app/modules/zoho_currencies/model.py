"""Zoho currencies mirror (docs/zoho-docs-md/currency.md).

An O1 master: owned by Zoho, read-only here, referenced by contacts, items and
every document (``currency_id``). Composes the split mixins — Identity +
Mirror — so the apply gate can fence, hash and tombstone it.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import DeactivationMixin, IntPKMixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin


class ZohoCurrency(IntPKMixin, TenantEntityMixin, DeactivationMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "zoho_currencies"

    currency_code: Mapped[str | None] = mapped_column(String(100), index=True)
    currency_name: Mapped[str | None] = mapped_column(String(255))
    currency_symbol: Mapped[str | None] = mapped_column(String(16))
    currency_format: Mapped[str | None] = mapped_column(String(100))
    price_precision: Mapped[int | None] = mapped_column(Integer)
    is_base_currency: Mapped[bool | None] = mapped_column(Boolean)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    effective_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        Index(
            "uq_zoho_currencies_zoho_id_live", "tenant_id", "zoho_id", unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
