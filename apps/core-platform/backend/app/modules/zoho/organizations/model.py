"""Zoho Organizations mirror table (docs/zoho-docs-md/organizations.md).

Column doctrine: every business column nullable (a thin Zoho payload must
never fail the sync); extracted columns cover everything the FSA/Delivery
apps filter or join on; the full document lives in ``zoho_raw`` (JSONB, via
ZohoEntityMixin) so nothing Zoho sends is ever lost.
"""

from datetime import date

from sqlalchemy import Boolean, Date, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.mixins import ZohoEntityMixin


class ZohoOrganization(IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin, ZohoEntityMixin, Base):
    __tablename__ = "zoho_organizations"

    # ── Identity & contact ──────────────────────────────────────────────────
    name: Mapped[str | None] = mapped_column(String(255), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(255))

    # ── Organization state ──────────────────────────────────────────────────
    is_default_org: Mapped[bool | None] = mapped_column(Boolean)
    is_org_active: Mapped[bool | None] = mapped_column(Boolean)
    user_role: Mapped[str | None] = mapped_column(String(100))
    user_status: Mapped[str | None] = mapped_column(String(50))
    account_created_date: Mapped[date | None] = mapped_column(Date)
    industry_type: Mapped[str | None] = mapped_column(String(100))
    industry_size: Mapped[str | None] = mapped_column(String(100))

    # ── Locale / formats ────────────────────────────────────────────────────
    language_code: Mapped[str | None] = mapped_column(String(10))
    time_zone: Mapped[str | None] = mapped_column(String(64))
    date_format: Mapped[str | None] = mapped_column(String(50))
    field_separator: Mapped[str | None] = mapped_column(String(10))
    fiscal_year_start_month: Mapped[int | None] = mapped_column(Integer)
    tax_group_enabled: Mapped[bool | None] = mapped_column(Boolean)

    # ── Currency ────────────────────────────────────────────────────────────
    currency_id: Mapped[str | None] = mapped_column(String(50))
    currency_code: Mapped[str | None] = mapped_column(String(10))
    currency_symbol: Mapped[str | None] = mapped_column(String(10))
    currency_format: Mapped[str | None] = mapped_column(String(50))
    price_precision: Mapped[int | None] = mapped_column(Integer)

    # ── Billing address (flattened from the nested `address` object) ───────
    address_street1: Mapped[str | None] = mapped_column(String(255))
    address_street2: Mapped[str | None] = mapped_column(String(255))
    address_city: Mapped[str | None] = mapped_column(String(100))
    address_state: Mapped[str | None] = mapped_column(String(100))
    address_country: Mapped[str | None] = mapped_column(String(100))
    address_zip: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        # zoho_id unique among LIVE rows only — a soft-deleted ghost never
        # blocks the same organization from re-syncing (partial index).
        Index(
            "uq_zoho_organizations_zoho_id_live",
            "zoho_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
