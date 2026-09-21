"""``roles`` — tenant-scoped roles (``users.role_id`` finally points somewhere).

Each tenant owns its roles; ``(tenant_id, code)`` is unique among live roles.
``uq_roles_tenant_id (tenant_id, id)`` lets ``users`` declare the composite FK
``(tenant_id, role_id)`` so a user can never hold another tenant's role.

``permissions`` is the future RBAC payload (a list of permission strings);
today only the codes ``admin`` / ``owner`` carry meaning (TenantAdmin).
System roles (``is_system``) are seeded per tenant and cannot be deleted.
"""

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TenantEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin


class Role(IntPKMixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        Index("uq_roles_tenant_code_active", "tenant_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("status IN ('active','inactive')", name="chk_roles_status"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Stable key, e.g. admin, sales_rep")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
        comment="Permission strings (RBAC, enforced in a later phase)",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Seeded role — cannot be deleted or re-coded",
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} tenant={self.tenant_id} code={self.code!r}>"


#: Seeded for every tenant.
SYSTEM_ROLES: tuple[tuple[str, str, str], ...] = (
    ("owner", "Owner", "Owns the tenant; full control"),
    ("admin", "Administrator", "Manages organizations, roles and users of the tenant"),
    ("member", "Member", "Regular user"),
)
