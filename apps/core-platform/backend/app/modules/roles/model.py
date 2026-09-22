"""``roles`` — organization-scoped roles (``users.role_id`` finally points somewhere).

Each **organization** owns its roles; ``(tenant_id, organization_id, code)`` is
unique among live roles. ``uq_roles_tenant_org_id (tenant_id, organization_id,
id)`` lets ``users`` declare the composite FK
``(tenant_id, organization_id, role_id)`` so a user can never hold another
organization's role.

``permissions`` is the future RBAC payload (a list of permission strings);
today only the codes ``admin`` / ``owner`` carry meaning. RBAC enforcement is
managed explicitly outside this schema. System roles (``is_system``) are seeded
per organization and cannot be deleted.
"""

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin


class Role(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        # Target of users' composite FK (tenant_id, organization_id, role_id).
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_roles_tenant_org_id"),
        Index("uq_roles_tenant_org_code_live", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("status IN ('active','inactive')", name="chk_roles_status"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Stable key, e.g. admin, sales_rep")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"),
        comment="Permission strings (RBAC, enforced outside this schema)",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Seeded role — cannot be deleted or re-coded",
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} tenant={self.tenant_id} org={self.organization_id} code={self.code!r}>"


#: Seeded for every organization.
SYSTEM_ROLES: tuple[tuple[str, str, str], ...] = (
    ("owner", "Owner", "Owns the organization; full control"),
    ("admin", "Administrator", "Manages the organization, roles and users"),
    ("member", "Member", "Regular user"),
)
