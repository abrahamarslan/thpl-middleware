"""``rbac`` — the permission catalogue, role permission sets and contextual grants.

    Permission      GLOBAL   the catalogue (code-owned, ``catalogue.py``; rows are
                             inserted-if-missing, never overwritten — like ``countries``)
    RolePermission  scoped   which permissions an EXPLICIT role holds (the computed
                             ``owner``/``admin`` roles have no rows)
    UserRole        ENTITY   a grant of a role to a user at a scope beyond the
                             user's base role (tenant / organization / department / team)

``public.roles`` stays where it is (``users.role_id`` points at it). A user's
effective permissions are the UNION of: their base role (home organization and
its descendants), their active ``UserRole`` rows, and the roles mapped from their
approved team memberships — see ``engine.py``.

Scope columns on ``UserRole`` are typed and real foreign keys (an untyped
``scope_id`` cannot be one), each tenant-safe and organization-pinned.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import (
    AppMetaMixin,
    AuditMixin,
    BigIntPKWithUUIDv7Mixin,
    IntPKMixin,
    MultiTenantMixin,
    TenantEntityMixin,
    TimestampMixin,
)
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.rbac.enums import RBAC_SCHEMA, AssignmentStatus, ScopeType, values
from app.modules.teams import model as _teams_model  # noqa: F401 — scope FK targets must exist in metadata

_CODE_FORMAT = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$"


class Permission(IntPKMixin, TimestampMixin, Base):
    """One atomic capability, ``module.resource:action``. GLOBAL reference data."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("permission_code", name="uq_permissions_code"),
        CheckConstraint(f"permission_code ~ '{_CODE_FORMAT}'", name="chk_permissions_code_format"),
        Index("ix_permissions_module_resource", "module_name", "resource_name"),
        {"schema": RBAC_SCHEMA, "comment": "Permission catalogue (GLOBAL; inserted-if-missing from catalogue.py)."},
    )

    module_name: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(50), nullable=False)
    action_name: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Generated from the three parts, so a code can never disagree with them.
    permission_code: Mapped[str] = mapped_column(
        String(160),
        Computed("module_name || '.' || resource_name || ':' || action_name", persisted=True),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )
    owner_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="Not granted by the computed 'admin' role — only 'owner' holds it",
    )
    deprecated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Left the catalogue; kept so old grants stay readable",
    )

    def __repr__(self) -> str:
        return f"<Permission {self.permission_code}>"


class RolePermission(IntPKMixin, MultiTenantMixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """A permission held by an EXPLICIT role. Scoped config: lifecycle belongs to the role."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "role_id"],
            ["roles.tenant_id", "roles.organization_id", "roles.id"],
            name="fk_role_permissions_role", ondelete="CASCADE",
        ),
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),
        Index("ix_role_permissions_role", "role_id"),
        Index("ix_role_permissions_permission", "permission_id"),
        {"schema": RBAC_SCHEMA, "comment": "Permissions held by explicit roles."},
    )

    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    permission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{RBAC_SCHEMA}.permissions.id", ondelete="CASCADE"), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<RolePermission role={self.role_id} permission={self.permission_id}>"


class UserRole(BigIntPKWithUUIDv7Mixin, TenantEntityMixin, SoftDeleteFilteredMixin, Base):
    """A role granted to a user at a scope.

    ``organization_id`` IS the scope anchor: NULL = tenant-wide, set = that
    organization (± descendants) — or the organization that owns the department /
    team when the scope is one of those. The role itself may be owned by an
    ancestor organization (a role defined at a holding is usable in its subtree);
    that rule lives in ``service.assign_role``, not in an FK.
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"],
            name="fk_user_roles_user", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"],
            name="fk_user_roles_role", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "department_id"],
            ["teams.departments.tenant_id", "teams.departments.organization_id", "teams.departments.id"],
            name="fk_user_roles_department", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "organization_id", "team_id"],
            ["teams.teams.tenant_id", "teams.teams.organization_id", "teams.teams.id"],
            name="fk_user_roles_team", ondelete="RESTRICT",
        ),
        CheckConstraint(f"scope_type IN ({values(ScopeType)})", name="chk_user_roles_scope_type"),
        CheckConstraint(f"status IN ({values(AssignmentStatus)})", name="chk_user_roles_status"),
        # Exactly the columns the scope names, and nothing else.
        CheckConstraint(
            "(scope_type = 'tenant' AND organization_id IS NULL AND department_id IS NULL AND team_id IS NULL)"
            " OR (scope_type = 'organization' AND organization_id IS NOT NULL"
            "     AND department_id IS NULL AND team_id IS NULL)"
            " OR (scope_type = 'department' AND organization_id IS NOT NULL"
            "     AND department_id IS NOT NULL AND team_id IS NULL)"
            " OR (scope_type = 'team' AND organization_id IS NOT NULL"
            "     AND team_id IS NOT NULL AND department_id IS NULL)",
            name="chk_user_roles_scope_columns",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_user_roles_window"),
        # One open-ended active grant per (user, role, scope). History (revoked / ended rows) never collides.
        Index(
            "uq_user_roles_open", "tenant_id", "user_id", "role_id", "scope_type",
            text("coalesce(organization_id, 0)"), text("coalesce(department_id, 0)"),
            text("coalesce(team_id, 0)"), unique=True,
            postgresql_where=text("deleted_at IS NULL AND status = 'active' AND valid_to IS NULL"),
        ),
        Index("ix_user_roles_user", "tenant_id", "user_id", postgresql_where=text("deleted_at IS NULL")),
        Index("ix_user_roles_role", "role_id", postgresql_where=text("deleted_at IS NULL")),
        {"schema": RBAC_SCHEMA, "comment": "Contextual role grants: tenant / organization / department / team scope."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ScopeType.ORGANIZATION.value,
        server_default=text("'organization'"),
    )
    department_id: Mapped[int | None] = mapped_column(BigInteger)
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    include_descendants: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="Also applies to child organizations / departments / teams of the scope node",
    )
    valid_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    valid_to: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="NULL = until revoked; a grant that ends is history, not deleted",
    )
    reason: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<UserRole user={self.user_id} role={self.role_id} {self.scope_type} org={self.organization_id}>"
