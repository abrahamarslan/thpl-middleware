"""Zoho locations mirror (docs/zoho-docs-md/locations.md).

An O1 master: business locations/branches (and, with Zoho Inventory's
unified locations, warehouses). Referenced by every Inventory document and by
item stock per location. Read-only here; Identity + Mirror mixins.
"""

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin


class ZohoLocation(IntPKMixin, TenantEntityMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "zoho_locations"

    location_name: Mapped[str | None] = mapped_column(String(255), index=True)
    type: Mapped[str | None] = mapped_column(String(50))                 # general | line_item_only
    zoho_status: Mapped[str | None] = mapped_column(String(20), index=True)   # Zoho's: active | inactive
    is_primary: Mapped[bool | None] = mapped_column(Boolean)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    parent_location_id: Mapped[str | None] = mapped_column(String(50), index=True)
    tax_settings_id: Mapped[str | None] = mapped_column(String(50))      # India: GSTIN settings
    auto_number_generation_id: Mapped[str | None] = mapped_column(String(50))
    is_all_users_selected: Mapped[bool | None] = mapped_column(Boolean)
    associated_series_ids: Mapped[list | None] = mapped_column(JSONB)
    associated_users: Mapped[list | None] = mapped_column(JSONB)         # [{user_id, user_name}]

    # Address (flattened from the nested `address` object)
    address_attention: Mapped[str | None] = mapped_column(String(255))
    address_street1: Mapped[str | None] = mapped_column(String(255))
    address_street2: Mapped[str | None] = mapped_column(String(255))
    address_city: Mapped[str | None] = mapped_column(String(100))
    address_state: Mapped[str | None] = mapped_column(String(100))
    address_state_code: Mapped[str | None] = mapped_column(String(10))
    address_country: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        Index(
            "uq_zoho_locations_zoho_id_live", "tenant_id", "zoho_id", unique=True,
            postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL"),
        ),
    )
