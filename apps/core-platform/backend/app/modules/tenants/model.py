"""``org_management.tenants`` — the ROOT of the multi-tenant model.

Every tenant-scoped table scopes to a row here through ``tenant_id``
(TenantScopedMixin: FK RESTRICT). Follows the approved DDL (IDENTITY id with
``id > 0``, public ``uuid``, soft-delete-aware unique code/domain) plus the
platform's common columns (docs/tenancy/README.md §2):

  * ``created_by`` / ``updated_by`` are plain BIGINTs with NO foreign key —
    a tenant exists before any of its users, and ``primary_user_id`` would
    otherwise form a tenants ↔ users cycle; user references here are soft.
  * ``created_by_name``, ``row_version`` (optimistic lock), ``app_version`` /
    ``app_metadata``, ``deleted_by`` / ``deleted_reason``, ``is_verified``.
  * A tenant has NO ``tenant_id`` of its own (GLOBAL table class).
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base
from app.database.mixins import (
    ORG_SCHEMA,
    AppMetaMixin,
    AuditMixin,
    RowVersionMixin,
    StatusMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin

if TYPE_CHECKING:
    from app.modules.organizations.model import Organization


class Tenant(AuditMixin, StatusMixin, RowVersionMixin, AppMetaMixin, TimestampMixin, SoftDeleteFilteredMixin, Base):
    """A customer account. Root of the tenant → organization tree."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("uuid", name="uq_tenants_uuid"),
        CheckConstraint("id > 0", name="chk_tenants_id_positive"),
        CheckConstraint("status IN ('trial','active','suspended','cancelled')", name="chk_tenants_status"),
        # Soft-delete-aware uniqueness: a code/domain frees up once its owner is deleted.
        Index("uq_tenants_code_active", "tenant_code", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_tenants_domain_active", "domain", unique=True,
              postgresql_where=text("deleted_at IS NULL AND domain IS NOT NULL")),
        {"schema": ORG_SCHEMA,
         "comment": "The root of the multi-tenant model. All downstream data scopes to these records."},
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True,
        comment="Internal fast-join primary key for relational integrity.",
    )
    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid_lib.uuid4, server_default=text("gen_random_uuid()"),
        comment="Public identifier for API exposure and cross-module polymorphic links.",
    )
    tenant_code: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Human-readable short code (e.g., THPL). Must be unique among active tenants.",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="Full legal or display name.")
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UTC", server_default=text("'UTC'"),
        comment="Default operational timezone for the tenant (e.g., Asia/Kolkata).",
    )
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, default="en-US", server_default=text("'en-US'"),
        comment="Default locale for formatting and UI translations (e.g., en-US).",
    )
    primary_contact_email: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Administrative email for critical system and billing alerts.",
    )
    domain: Mapped[str | None] = mapped_column(
        String(255), comment="Optional custom domain for white-labeled routing (e.g., portal.tenant.com).",
    )
    primary_user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Core admin user who owns this tenant space (soft reference).",
    )
    custom_attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment="Tenant-specific configuration or unmapped fields.",
    )

    organizations: Mapped[list[Organization]] = relationship(
        back_populates="tenant", foreign_keys="Organization.tenant_id", viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} code={self.tenant_code!r} status={self.status!r}>"


# Both sides of Tenant ↔ Organization must be mapped before mappers configure,
# whichever module is imported first (this import is safe: Tenant is defined).
import app.modules.organizations.model  # noqa: E402,F401
