"""``roles`` — organization-scoped roles (``users.role_id`` points here).

Each **organization** owns its roles; ``(tenant_id, organization_id, code)`` is
unique among live roles. ``uq_roles_tenant_org_id (tenant_id, organization_id,
id)`` lets ``users`` declare the composite FK
``(tenant_id, organization_id, role_id)`` so a user's BASE role is always one
of their own organization's. ``uq_roles_tenant_id (tenant_id, id)`` is the
tenant-safe target for contextual grants (``rbac.user_roles``) and team roles,
which may use a role owned by an ancestor organization.

What a role may DO is not stored here: ``grant_mode`` says how its permission
set is determined (``all`` / ``all_but_owner_only`` are computed from the
catalogue; ``explicit`` roles own ``rbac.role_permissions`` rows) — see
``app/modules/rbac`` and docs/rbac-module.md. System roles (``is_system``) are
seeded per organization from ``rbac.templates`` and cannot be deleted.
"""

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.rbac.enums import GrantMode, RoleStatus, values


class Role(IntPKMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        # Target of users' composite FK (tenant_id, organization_id, role_id).
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_roles_tenant_org_id"),
        # Tenant-safe target for grants that may use an ancestor organization's role.
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id"),
        Index("uq_roles_tenant_org_code_live", "tenant_id", "organization_id", "code", unique=True,
              postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint(f"status IN ({values(RoleStatus)})", name="chk_roles_status"),
        CheckConstraint(f"grant_mode IN ({values(GrantMode)})", name="chk_roles_grant_mode"),
        CheckConstraint("hierarchy_level >= 0", name="chk_roles_hierarchy_level"),
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Stable key, e.g. admin, sales_rep")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Seeded role — cannot be deleted or re-coded; its permission set is code-owned",
    )
    grant_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default=GrantMode.EXPLICIT.value, server_default=text("'explicit'"),
        comment="explicit (role_permissions rows) | all | all_but_owner_only (computed from the catalogue)",
    )
    hierarchy_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="Escalation guard: an actor may only grant roles below the highest level they hold",
    )
    is_assignable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="False = cannot be granted through the API (e.g. a retired template)",
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} tenant={self.tenant_id} org={self.organization_id} code={self.code!r}>"
