"""Zoho Books users mirror (docs/zoho-docs-md/users.md).

NOT the application's own ``users`` table — these are the people who have a
login in the Zoho organization (salespersons, approvers, location users).
Documents reference them by Zoho user id (``salesperson_id``,
``created_by_id``, location ``associated_users``). Package ``zoho_users`` to
keep ``app.modules.users`` (our accounts) unambiguous.

Linking a Zoho user to a local account (by email) is deliberately left out:
it is an identity decision, not a mirror concern.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin


class ZohoUser(IntPKMixin, TenantEntityMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "zoho_users"

    name: Mapped[str | None] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    user_role: Mapped[str | None] = mapped_column(String(100))
    role_id: Mapped[str | None] = mapped_column(String(50))
    zoho_status: Mapped[str | None] = mapped_column(String(20), index=True)   # Zoho's: active | inactive | invited | deleted
    user_type: Mapped[str | None] = mapped_column(String(50))
    is_current_user: Mapped[bool | None] = mapped_column(Boolean)
    is_customer_segmented: Mapped[bool | None] = mapped_column(Boolean)
    is_vendor_segmented: Mapped[bool | None] = mapped_column(Boolean)
    photo_url: Mapped[str | None] = mapped_column(Text)
    cost_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    zoho_created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_zoho_users_zoho_id_live", "tenant_id", "zoho_id", unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
