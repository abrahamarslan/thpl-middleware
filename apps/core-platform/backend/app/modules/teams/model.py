"""``teams`` — departments, job titles, team types/roles, teams and memberships.

    Department   ENTITY  org-owned tree (nested-set + path via ``app.common.tree``)
    JobTitle     ENTITY  org-owned catalogue, optionally under a department
    TeamType     ENTITY  org-owned classification tree
    TeamRole     ENTITY  what a member IS in a team; may map to an RBAC role
    Team         ENTITY  org-owned tree of operational teams
    UserTeam     ENTITY  membership: effective-dated, approval-gated, cross-org allowed

Scoping (docs/rbac-module.md §3.4)
----------------------------------
* every table is organization-owned (``OrgEntityMixin``: tenant + organization NOT NULL);
* every reference between tenant tables is a COMPOSITE foreign key, so the database — not
  only the ORM — refuses a row that points at another tenant's parent, type or user;
* hierarchy and membership FKs also pin the ORGANIZATION ``(tenant_id, organization_id, id)``
  (a team cannot sit under another organization's team). Cross-organization *membership* is
  deliberate: a user (any organization of the tenant) belongs to a team through ``user_id``
  pinned only to the tenant, while the membership's organization is the TEAM's.
* uniqueness is LIVE-only (``deleted_at IS NULL``) and, for memberships, OPEN-only
  (``valid_until IS NULL``): history must never block a re-join (the ``place_links`` lesson).
* no cycle triggers: the tree routine refuses cycles (``TreeError``), and CHECKs refuse
  self-parents — the same design as ``categories``.

Where a department or team sits is NOT stored here: it is a ``geo.place_links`` row with
``owner_type`` ``department`` / ``team`` (floor/room in the link's ``custom_attributes``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDv7Mixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.custom_fields.mixins import HasCustomFieldsMixin
from app.modules.tags.mixins import HasTagsMixin
from app.modules.teams.enums import (
    TEAMS_SCHEMA,
    ApprovalStatus,
    CatalogueStatus,
    DepartmentStatus,
    MembershipStatus,
    TeamStatus,
    values,
)

_LIVE = text("deleted_at IS NULL")


def _fk(name: str, cols: list[str], target: str, target_cols: list[str], ondelete: str = "RESTRICT"):
    """Composite FK helper: ``target`` is ``schema.table`` (or a bare public table)."""
    return ForeignKeyConstraint(cols, [f"{target}.{c}" for c in target_cols], name=name, ondelete=ondelete)


def _org_fk(name: str, col: str, target: str, ondelete: str = "RESTRICT"):
    """``(tenant, organization, <col>) → target(tenant, organization, id)`` — same tenant AND organization."""
    return _fk(name, ["tenant_id", "organization_id", col], target,
               ["tenant_id", "organization_id", "id"], ondelete)


def _user_fk(name: str, col: str, ondelete: str = "RESTRICT"):
    """``(tenant, <col>) → users(tenant, id)`` — same tenant (users have a home organization of their own)."""
    return _fk(name, ["tenant_id", col], "users", ["tenant_id", "id"], ondelete)


class TreeColumns:
    """The tree columns ``app.common.tree.recompute_bounds`` writes (and only it).

    ``slug`` (read by the routine to build ``path``) is each model's code, lower-cased.
    """

    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="NULL = a root")
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    path: Mapped[str | None] = mapped_column(Text, comment="Text breadcrumb '/code/code/', maintained by tree.py")
    lft: Mapped[int] = mapped_column("_lft", Integer, nullable=False, default=0, server_default=text("0"))
    rgt: Mapped[int] = mapped_column("_rgt", Integer, nullable=False, default=0, server_default=text("0"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


def _tree_checks(table: str) -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name=f"chk_{table}_not_own_parent"),
        CheckConstraint("NOT (is_root AND parent_id IS NOT NULL)", name=f"chk_{table}_root_no_parent"),
        CheckConstraint("_rgt >= _lft", name=f"chk_{table}_nested_set_bounds"),
        CheckConstraint("depth >= 0", name=f"chk_{table}_depth_nonneg"),
    )


def _tree_index(table: str) -> Index:
    return Index(f"ix_{table}_scope_lft_rgt", "tenant_id", "organization_id", "_lft", "_rgt",
                 postgresql_where=_LIVE)


class Department(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, TreeColumns, HasCustomFieldsMixin, HasTagsMixin,
    SoftDeleteFilteredMixin, Base,
):
    """A formal organizational unit (Sales, Operations, Finance) of one organization."""

    __tablename__ = "departments"
    custom_fields_owner_type = "department"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_departments_tenant_org_id"),
        _org_fk("fk_departments_parent", "parent_id", f"{TEAMS_SCHEMA}.departments"),
        _user_fk("fk_departments_head", "head_of_department_user_id",
                 ondelete="SET NULL (head_of_department_user_id)"),
        CheckConstraint(f"status IN ({values(DepartmentStatus)})", name="chk_departments_status"),
        *_tree_checks("departments"),
        Index("uq_departments_code_live", "tenant_id", "organization_id", "department_code",
              unique=True, postgresql_where=_LIVE),
        Index("ix_departments_parent", "parent_id", postgresql_where=text("parent_id IS NOT NULL")),
        Index("ix_departments_head", "head_of_department_user_id",
              postgresql_where=text("head_of_department_user_id IS NOT NULL")),
        Index("ix_departments_name_trgm", "department_name", postgresql_using="gin",
              postgresql_ops={"department_name": "gin_trgm_ops"}, postgresql_where=_LIVE),
        _tree_index("departments"),
        {"schema": TEAMS_SCHEMA, "comment": "Departments: an organization-owned tree (nested-set + path)."},
    )

    department_code: Mapped[str] = mapped_column(String(50), nullable=False)
    department_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    head_of_department_user_id: Mapped[int | None] = mapped_column(BigInteger)
    cost_center_code: Mapped[str | None] = mapped_column(String(50))

    @property
    def slug(self) -> str:
        return self.department_code.lower()

    def __repr__(self) -> str:
        return f"<Department id={self.id} org={self.organization_id} code={self.department_code!r}>"


class JobTitle(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A standardized job title / designation, optionally under a department."""

    __tablename__ = "job_titles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_job_titles_tenant_org_id"),
        _org_fk("fk_job_titles_department", "department_id", f"{TEAMS_SCHEMA}.departments"),
        CheckConstraint(f"status IN ({values(CatalogueStatus)})", name="chk_job_titles_status"),
        CheckConstraint("band_level >= 0", name="chk_job_titles_band"),
        Index("uq_job_titles_code_live", "tenant_id", "organization_id", "job_code",
              unique=True, postgresql_where=_LIVE),
        Index("ix_job_titles_department", "department_id", postgresql_where=text("department_id IS NOT NULL")),
        Index("ix_job_titles_title_trgm", "title", postgresql_using="gin",
              postgresql_ops={"title": "gin_trgm_ops"}, postgresql_where=_LIVE),
        {"schema": TEAMS_SCHEMA, "comment": "Job titles / designations."},
    )

    job_code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[int | None] = mapped_column(BigInteger)
    band_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_management: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )

    def __repr__(self) -> str:
        return f"<JobTitle id={self.id} org={self.organization_id} code={self.job_code!r}>"


class TeamType(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, TreeColumns, SoftDeleteFilteredMixin, Base):
    """A classification of teams (e.g. Delivery → Last-mile), itself a tree."""

    __tablename__ = "team_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_team_types_tenant_org_id"),
        _org_fk("fk_team_types_parent", "parent_id", f"{TEAMS_SCHEMA}.team_types"),
        CheckConstraint(f"status IN ({values(CatalogueStatus)})", name="chk_team_types_status"),
        *_tree_checks("team_types"),
        Index("uq_team_types_code_live", "tenant_id", "organization_id", "type_code",
              unique=True, postgresql_where=_LIVE),
        Index("ix_team_types_parent", "parent_id", postgresql_where=text("parent_id IS NOT NULL")),
        _tree_index("team_types"),
        {"schema": TEAMS_SCHEMA, "comment": "Team types: an organization-owned classification tree."},
    )

    type_code: Mapped[str] = mapped_column(String(50), nullable=False)
    type_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100))
    icon_class: Mapped[str | None] = mapped_column(String(100))

    @property
    def slug(self) -> str:
        return self.type_code.lower()

    def __repr__(self) -> str:
        return f"<TeamType id={self.id} org={self.organization_id} code={self.type_code!r}>"


class TeamRole(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """What a member IS in a team (lead, coordinator). Not an RBAC role — but may map to one.

    ``rbac_role_id`` is the ONE mechanism by which a team role carries permissions: while the
    membership is approved and in window, the member holds that role SCOPED TO THE TEAM.
    ``is_default`` (one per team type) replaces the pasted ``team_types.default_team_role_id``,
    which made ``team_types`` ↔ ``team_roles`` a circular foreign key.
    """

    __tablename__ = "team_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_team_roles_tenant_org_id"),
        _org_fk("fk_team_roles_team_type", "team_type_id", f"{TEAMS_SCHEMA}.team_types"),
        _fk("fk_team_roles_rbac_role", ["tenant_id", "rbac_role_id"], "roles", ["tenant_id", "id"]),
        CheckConstraint(f"status IN ({values(CatalogueStatus)})", name="chk_team_roles_status"),
        CheckConstraint("hierarchy_level >= 0", name="chk_team_roles_level"),
        Index("uq_team_roles_code_live", "tenant_id", "organization_id", "role_code",
              text("coalesce(team_type_id, 0)"), unique=True, postgresql_where=_LIVE),
        # At most one default role per team type (and one type-less default).
        Index("uq_team_roles_default_per_type", "tenant_id", "organization_id",
              text("coalesce(team_type_id, 0)"), unique=True,
              postgresql_where=text("is_default AND deleted_at IS NULL")),
        Index("ix_team_roles_team_type", "team_type_id", postgresql_where=text("team_type_id IS NOT NULL")),
        Index("ix_team_roles_rbac_role", "rbac_role_id", postgresql_where=text("rbac_role_id IS NOT NULL")),
        {"schema": TEAMS_SCHEMA, "comment": "Roles a user can hold within a team."},
    )

    role_code: Mapped[str] = mapped_column(String(50), nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    team_type_id: Mapped[int | None] = mapped_column(BigInteger)
    hierarchy_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_assignable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
        comment="The role a new member of a team of this type gets when none is named",
    )
    rbac_role_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="RBAC role the member holds, scoped to this team, while the membership is in force",
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    color_code: Mapped[str | None] = mapped_column(String(20))
    icon_class: Mapped[str | None] = mapped_column(String(100))

    def __repr__(self) -> str:
        return f"<TeamRole id={self.id} org={self.organization_id} code={self.role_code!r}>"


class Team(
    BigIntPKWithUUIDv7Mixin, OrgEntityMixin, TreeColumns, HasCustomFieldsMixin, HasTagsMixin,
    SoftDeleteFilteredMixin, Base,
):
    """An operational or functional team, structured hierarchically."""

    __tablename__ = "teams"
    custom_fields_owner_type = "team"
    __table_args__ = (
        UniqueConstraint("tenant_id", "organization_id", "id", name="uq_teams_tenant_org_id"),
        _org_fk("fk_teams_parent", "parent_id", f"{TEAMS_SCHEMA}.teams"),
        _org_fk("fk_teams_team_type", "team_type_id", f"{TEAMS_SCHEMA}.team_types"),
        _org_fk("fk_teams_department", "department_id", f"{TEAMS_SCHEMA}.departments"),
        _user_fk("fk_teams_lead", "team_lead_user_id", ondelete="SET NULL (team_lead_user_id)"),
        CheckConstraint(f"status IN ({values(TeamStatus)})", name="chk_teams_status"),
        *_tree_checks("teams"),
        Index("uq_teams_code_live", "tenant_id", "organization_id", "team_code",
              unique=True, postgresql_where=_LIVE),
        Index("ix_teams_parent", "parent_id", postgresql_where=text("parent_id IS NOT NULL")),
        Index("ix_teams_team_type", "team_type_id"),
        Index("ix_teams_department", "department_id", postgresql_where=text("department_id IS NOT NULL")),
        Index("ix_teams_lead", "team_lead_user_id", postgresql_where=text("team_lead_user_id IS NOT NULL")),
        Index("ix_teams_name_trgm", "team_name", postgresql_using="gin",
              postgresql_ops={"team_name": "gin_trgm_ops"}, postgresql_where=_LIVE),
        _tree_index("teams"),
        {"schema": TEAMS_SCHEMA, "comment": "Teams: an organization-owned tree of operational teams."},
    )

    team_code: Mapped[str] = mapped_column(String(50), nullable=False)
    team_name: Mapped[str] = mapped_column(String(150), nullable=False)
    team_type_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    team_lead_user_id: Mapped[int | None] = mapped_column(BigInteger)
    department_id: Mapped[int | None] = mapped_column(BigInteger)
    email_address: Mapped[str | None] = mapped_column(String(255))
    operational_goal: Mapped[str | None] = mapped_column(Text)
    color_code: Mapped[str | None] = mapped_column(String(20))
    icon_class: Mapped[str | None] = mapped_column(String(100))
    # Reserved / display data — no logic until a performance engine exists (docs/rbac-module.md D6).
    # Read-only through the API.
    has_targets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    has_incentives: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    achievement_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), comment="Display cache; the authoritative metric belongs to a future performance engine",
    )
    performance_last_updated: Mapped[dt.date | None] = mapped_column(Date)
    performance_last_calculated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def slug(self) -> str:
        return self.team_code.lower()

    def __repr__(self) -> str:
        return f"<Team id={self.id} org={self.organization_id} code={self.team_code!r}>"


class UserTeam(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    """A user's membership of a team.

    ``organization_id`` is the TEAM's organization (composite FK), while ``user_id`` is pinned
    only to the tenant — so a user of any organization can join. It grants nothing until
    ``approval_status = 'approved'``, ``status = 'active'`` and now is within
    ``[valid_from, valid_until)``. Leaving closes ``valid_until``; rejoining inserts a new row.
    """

    __tablename__ = "user_teams"
    __table_args__ = (
        _user_fk("fk_user_teams_user", "user_id", ondelete="CASCADE"),
        _org_fk("fk_user_teams_team", "team_id", f"{TEAMS_SCHEMA}.teams"),
        _org_fk("fk_user_teams_team_role", "team_role_id", f"{TEAMS_SCHEMA}.team_roles"),
        CheckConstraint(f"status IN ({values(MembershipStatus)})", name="chk_user_teams_status"),
        CheckConstraint(f"approval_status IN ({values(ApprovalStatus)})", name="chk_user_teams_approval_status"),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="chk_user_teams_window"),
        # One OPEN membership per (user, team, role); ended ones are history.
        Index("uq_user_teams_open", "tenant_id", "user_id", "team_id", text("coalesce(team_role_id, 0)"),
              unique=True, postgresql_where=text("valid_until IS NULL AND deleted_at IS NULL")),
        # At most one primary team per user at a time.
        Index("uq_user_teams_one_primary", "tenant_id", "user_id", unique=True,
              postgresql_where=text("is_primary AND status = 'active' AND valid_until IS NULL "
                                    "AND deleted_at IS NULL")),
        Index("ix_user_teams_user", "tenant_id", "user_id", postgresql_where=_LIVE),
        Index("ix_user_teams_team", "team_id", postgresql_where=_LIVE),
        Index("ix_user_teams_team_role", "team_role_id", postgresql_where=text("team_role_id IS NOT NULL")),
        {"schema": TEAMS_SCHEMA, "comment": "Team memberships (effective-dated, approval-gated)."},
    )

    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_role_id: Mapped[int | None] = mapped_column(BigInteger)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()"),
    )
    valid_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), comment="NULL = ongoing; leaving a team closes it",
    )
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalStatus.APPROVED.value,
        server_default=text("'approved'"),
    )
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(BigInteger, comment="users.id (no FK: survives the user)")
    approval_notes: Mapped[str | None] = mapped_column(Text)
    # Reserved / display data — no logic (docs/rbac-module.md D6); read-only through the API.
    has_individual_targets: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    has_custom_incentives: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    individual_achievement_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))

    @property
    def is_in_force(self) -> bool:
        """Approved, active and inside its window right now."""
        now = dt.datetime.now(dt.UTC)
        return (
            self.approval_status == ApprovalStatus.APPROVED.value
            and self.status == MembershipStatus.ACTIVE.value
            and self.valid_from <= now
            and (self.valid_until is None or self.valid_until > now)
            and self.deleted_at is None
        )

    def __repr__(self) -> str:
        return f"<UserTeam id={self.id} user={self.user_id} team={self.team_id}>"
