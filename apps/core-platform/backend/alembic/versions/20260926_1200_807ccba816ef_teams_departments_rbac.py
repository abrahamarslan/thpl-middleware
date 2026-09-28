"""Teams, departments and RBAC (docs/rbac-module.md).

* schemas ``rbac`` and ``teams``;
* ``roles``: ``grant_mode`` / ``hierarchy_level`` / ``is_assignable``, a tenant-safe unique key, a wider
  status CHECK; the free-text ``permissions`` JSONB is BACKFILLED into ``rbac.role_permissions`` and dropped;
* ``rbac``: ``permissions`` (the catalogue, seeded here, insert-missing), ``role_permissions``, ``user_roles``;
* ``teams``: ``departments``, ``job_titles``, ``team_types``, ``team_roles``, ``teams``, ``user_teams``;
* ``hr.employment_records``: ``department_id`` / ``job_title_id`` (composite FKs) + a self-manager CHECK;
* ``geo.place_links``: departments and teams may own an address;
* ``core.entity_types``: ``department`` and ``team`` are registered (custom fields, aliases, tags).

Data steps (all idempotent, run before the ``permissions`` column is dropped):
  1. every organization gets the full system-role template set (owner / admin computed; the rest explicit);
  2. legacy ``roles.permissions`` strings of CUSTOM roles are moved to ``role_permissions`` where the code is in
     the catalogue; the raw list is kept in ``app_metadata.legacy_permissions``;
  3. users with NO role become ``member`` of their own organization (self-registered / SSO users would
     otherwise hold no grants once permissions are enforced);
  4. holders of a ROOT organization's ``owner`` role also get the tenant-wide ``owner`` grant.

Downgrade restores the schema (the dropped JSONB comes back empty) but cannot un-assign roles.

Revision ID: 807ccba816ef
Revises: e96a8bbffe38
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.modules.rbac.catalogue import ALL_CODES
from app.modules.rbac.seed import seed_permissions
from app.modules.rbac.templates import ROLE_TEMPLATES

revision: str = "807ccba816ef"
down_revision: str | None = "e96a8bbffe38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_TYPES = (
    "user", "organization", "department", "team", "customer", "contact_person", "vendor", "warehouse",
    "zoho_location", "invoice", "estimate", "sales_order", "purchase_order", "shipment",
)
_OLD_OWNER_TYPES = tuple(t for t in _OWNER_TYPES if t not in ("department", "team"))


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS rbac")
    op.execute("CREATE SCHEMA IF NOT EXISTS teams")

    # ── roles: what the new tables point at ─────────────────────────────────────
    op.add_column('roles', sa.Column('grant_mode', sa.String(length=30), server_default=sa.text("'explicit'"), nullable=False, comment='explicit (role_permissions rows) | all | all_but_owner_only (computed from the catalogue)'))
    op.add_column('roles', sa.Column('hierarchy_level', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Escalation guard: an actor may only grant roles below the highest level they hold'))
    op.add_column('roles', sa.Column('is_assignable', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='False = cannot be granted through the API (e.g. a retired template)'))
    op.alter_column('roles', 'is_system',
               existing_type=sa.BOOLEAN(),
               comment='Seeded role — cannot be deleted or re-coded; its permission set is code-owned',
               existing_comment='Seeded role — cannot be deleted or re-coded',
               existing_nullable=False,
               existing_server_default=sa.text('false'))
    op.create_unique_constraint('uq_roles_tenant_id', 'roles', ['tenant_id', 'id'])
    op.drop_constraint('chk_roles_status', 'roles', type_='check')
    op.create_check_constraint('chk_roles_status', 'roles', "status IN ('active','inactive','deprecated')")
    op.create_check_constraint('chk_roles_grant_mode', 'roles', "grant_mode IN ('explicit','all','all_but_owner_only')")
    op.create_check_constraint('chk_roles_hierarchy_level', 'roles', 'hierarchy_level >= 0')

    op.create_table('permissions',
    sa.Column('module_name', sa.String(length=50), nullable=False),
    sa.Column('resource_name', sa.String(length=50), nullable=False),
    sa.Column('action_name', sa.String(length=50), nullable=False),
    sa.Column('permission_code', sa.String(length=160), sa.Computed("module_name || '.' || resource_name || ':' || action_name", persisted=True), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_system', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('owner_only', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment="Not granted by the computed 'admin' role — only 'owner' holds it"),
    sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True, comment='Left the catalogue; kept so old grants stay readable'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("permission_code ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$'", name='chk_permissions_code_format'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('permission_code', name='uq_permissions_code'),
    schema='rbac',
    comment='Permission catalogue (GLOBAL; inserted-if-missing from catalogue.py).'
    )
    op.create_index('ix_permissions_module_resource', 'permissions', ['module_name', 'resource_name'], unique=False, schema='rbac')
    op.create_table('team_types',
    sa.Column('type_code', sa.String(length=50), nullable=False),
    sa.Column('type_name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=100), nullable=True),
    sa.Column('icon_class', sa.String(length=100), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True, comment='NULL = a root'),
    sa.Column('is_root', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('depth', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('path', sa.Text(), nullable=True, comment="Text breadcrumb '/code/code/', maintained by tree.py"),
    sa.Column('_lft', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('_rgt', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("status IN ('active','inactive','deprecated')", name='chk_team_types_status'),
    sa.CheckConstraint('NOT (is_root AND parent_id IS NOT NULL)', name='chk_team_types_root_no_parent'),
    sa.CheckConstraint('_rgt >= _lft', name='chk_team_types_nested_set_bounds'),
    sa.CheckConstraint('depth >= 0', name='chk_team_types_depth_nonneg'),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='chk_team_types_not_own_parent'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'parent_id'], ['teams.team_types.tenant_id', 'teams.team_types.organization_id', 'teams.team_types.id'], name='fk_team_types_parent', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_team_types_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_team_types_tenant_org_id'),
    schema='teams',
    comment='Team types: an organization-owned classification tree.'
    )
    op.create_index('ix_team_types_parent', 'team_types', ['parent_id'], unique=False, schema='teams', postgresql_where=sa.text('parent_id IS NOT NULL'))
    op.create_index('ix_team_types_scope_lft_rgt', 'team_types', ['tenant_id', 'organization_id', '_lft', '_rgt'], unique=False, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_team_types_tenant_org', 'team_types', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_types_deleted_at'), 'team_types', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_types_status'), 'team_types', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_types_tenant_id'), 'team_types', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_types_uuid'), 'team_types', ['uuid'], unique=True, schema='teams')
    op.create_index('uq_team_types_code_live', 'team_types', ['tenant_id', 'organization_id', 'type_code'], unique=True, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('role_permissions',
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.Column('permission_id', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['rbac.permissions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'role_id'], ['roles.tenant_id', 'roles.organization_id', 'roles.id'], name='fk_role_permissions_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_role_permissions_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permissions_pair'),
    schema='rbac',
    comment='Permissions held by explicit roles.'
    )
    op.create_index(op.f('ix_rbac_role_permissions_tenant_id'), 'role_permissions', ['tenant_id'], unique=False, schema='rbac')
    op.create_index('ix_role_permissions_permission', 'role_permissions', ['permission_id'], unique=False, schema='rbac')
    op.create_index('ix_role_permissions_role', 'role_permissions', ['role_id'], unique=False, schema='rbac')
    op.create_index('ix_role_permissions_tenant_org', 'role_permissions', ['tenant_id', 'organization_id'], unique=False, schema='rbac')
    op.create_table('team_roles',
    sa.Column('role_code', sa.String(length=50), nullable=False),
    sa.Column('role_name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('team_type_id', sa.BigInteger(), nullable=True),
    sa.Column('hierarchy_level', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('is_assignable', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='The role a new member of a team of this type gets when none is named'),
    sa.Column('rbac_role_id', sa.BigInteger(), nullable=True, comment='RBAC role the member holds, scoped to this team, while the membership is in force'),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('color_code', sa.String(length=20), nullable=True),
    sa.Column('icon_class', sa.String(length=100), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("status IN ('active','inactive','deprecated')", name='chk_team_roles_status'),
    sa.CheckConstraint('hierarchy_level >= 0', name='chk_team_roles_level'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'team_type_id'], ['teams.team_types.tenant_id', 'teams.team_types.organization_id', 'teams.team_types.id'], name='fk_team_roles_team_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_team_roles_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'rbac_role_id'], ['roles.tenant_id', 'roles.id'], name='fk_team_roles_rbac_role', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_team_roles_tenant_org_id'),
    schema='teams',
    comment='Roles a user can hold within a team.'
    )
    op.create_index('ix_team_roles_rbac_role', 'team_roles', ['rbac_role_id'], unique=False, schema='teams', postgresql_where=sa.text('rbac_role_id IS NOT NULL'))
    op.create_index('ix_team_roles_team_type', 'team_roles', ['team_type_id'], unique=False, schema='teams', postgresql_where=sa.text('team_type_id IS NOT NULL'))
    op.create_index('ix_team_roles_tenant_org', 'team_roles', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_roles_deleted_at'), 'team_roles', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_roles_status'), 'team_roles', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_roles_tenant_id'), 'team_roles', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_team_roles_uuid'), 'team_roles', ['uuid'], unique=True, schema='teams')
    op.create_index('uq_team_roles_code_live', 'team_roles', ['tenant_id', 'organization_id', 'role_code', sa.literal_column('coalesce(team_type_id, 0)')], unique=True, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_team_roles_default_per_type', 'team_roles', ['tenant_id', 'organization_id', sa.literal_column('coalesce(team_type_id, 0)')], unique=True, schema='teams', postgresql_where=sa.text('is_default AND deleted_at IS NULL'))
    op.create_table('departments',
    sa.Column('department_code', sa.String(length=50), nullable=False),
    sa.Column('department_name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('head_of_department_user_id', sa.BigInteger(), nullable=True),
    sa.Column('cost_center_code', sa.String(length=50), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True, comment='NULL = a root'),
    sa.Column('is_root', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('depth', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('path', sa.Text(), nullable=True, comment="Text breadcrumb '/code/code/', maintained by tree.py"),
    sa.Column('_lft', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('_rgt', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("status IN ('active','inactive','archived')", name='chk_departments_status'),
    sa.CheckConstraint('NOT (is_root AND parent_id IS NOT NULL)', name='chk_departments_root_no_parent'),
    sa.CheckConstraint('_rgt >= _lft', name='chk_departments_nested_set_bounds'),
    sa.CheckConstraint('depth >= 0', name='chk_departments_depth_nonneg'),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='chk_departments_not_own_parent'),
    sa.ForeignKeyConstraint(['tenant_id', 'head_of_department_user_id'], ['users.tenant_id', 'users.id'], name='fk_departments_head', ondelete='SET NULL (head_of_department_user_id)'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'parent_id'], ['teams.departments.tenant_id', 'teams.departments.organization_id', 'teams.departments.id'], name='fk_departments_parent', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_departments_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_departments_tenant_org_id'),
    schema='teams',
    comment='Departments: an organization-owned tree (nested-set + path).'
    )
    op.create_index('ix_departments_head', 'departments', ['head_of_department_user_id'], unique=False, schema='teams', postgresql_where=sa.text('head_of_department_user_id IS NOT NULL'))
    op.create_index('ix_departments_name_trgm', 'departments', ['department_name'], unique=False, schema='teams', postgresql_using='gin', postgresql_ops={'department_name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_departments_parent', 'departments', ['parent_id'], unique=False, schema='teams', postgresql_where=sa.text('parent_id IS NOT NULL'))
    op.create_index('ix_departments_scope_lft_rgt', 'departments', ['tenant_id', 'organization_id', '_lft', '_rgt'], unique=False, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_departments_tenant_org', 'departments', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_departments_deleted_at'), 'departments', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_departments_status'), 'departments', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_departments_tenant_id'), 'departments', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_departments_uuid'), 'departments', ['uuid'], unique=True, schema='teams')
    op.create_index('uq_departments_code_live', 'departments', ['tenant_id', 'organization_id', 'department_code'], unique=True, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('job_titles',
    sa.Column('job_code', sa.String(length=50), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('band_level', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('is_management', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("status IN ('active','inactive','deprecated')", name='chk_job_titles_status'),
    sa.CheckConstraint('band_level >= 0', name='chk_job_titles_band'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'department_id'], ['teams.departments.tenant_id', 'teams.departments.organization_id', 'teams.departments.id'], name='fk_job_titles_department', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_job_titles_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_job_titles_tenant_org_id'),
    schema='teams',
    comment='Job titles / designations.'
    )
    op.create_index('ix_job_titles_department', 'job_titles', ['department_id'], unique=False, schema='teams', postgresql_where=sa.text('department_id IS NOT NULL'))
    op.create_index('ix_job_titles_tenant_org', 'job_titles', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index('ix_job_titles_title_trgm', 'job_titles', ['title'], unique=False, schema='teams', postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_teams_job_titles_deleted_at'), 'job_titles', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_job_titles_status'), 'job_titles', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_job_titles_tenant_id'), 'job_titles', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_job_titles_uuid'), 'job_titles', ['uuid'], unique=True, schema='teams')
    op.create_index('uq_job_titles_code_live', 'job_titles', ['tenant_id', 'organization_id', 'job_code'], unique=True, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('teams',
    sa.Column('team_code', sa.String(length=50), nullable=False),
    sa.Column('team_name', sa.String(length=150), nullable=False),
    sa.Column('team_type_id', sa.BigInteger(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('team_lead_user_id', sa.BigInteger(), nullable=True),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('email_address', sa.String(length=255), nullable=True),
    sa.Column('operational_goal', sa.Text(), nullable=True),
    sa.Column('color_code', sa.String(length=20), nullable=True),
    sa.Column('icon_class', sa.String(length=100), nullable=True),
    sa.Column('has_targets', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('has_incentives', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('achievement_ratio', sa.Numeric(precision=8, scale=2), nullable=True, comment='Display cache; the authoritative metric belongs to a future performance engine'),
    sa.Column('performance_last_updated', sa.Date(), nullable=True),
    sa.Column('performance_last_calculated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True, comment='NULL = a root'),
    sa.Column('is_root', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('depth', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('path', sa.Text(), nullable=True, comment="Text breadcrumb '/code/code/', maintained by tree.py"),
    sa.Column('_lft', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('_rgt', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("status IN ('active','inactive','archived','pending')", name='chk_teams_status'),
    sa.CheckConstraint('NOT (is_root AND parent_id IS NOT NULL)', name='chk_teams_root_no_parent'),
    sa.CheckConstraint('_rgt >= _lft', name='chk_teams_nested_set_bounds'),
    sa.CheckConstraint('depth >= 0', name='chk_teams_depth_nonneg'),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name='chk_teams_not_own_parent'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'department_id'], ['teams.departments.tenant_id', 'teams.departments.organization_id', 'teams.departments.id'], name='fk_teams_department', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'parent_id'], ['teams.teams.tenant_id', 'teams.teams.organization_id', 'teams.teams.id'], name='fk_teams_parent', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'team_type_id'], ['teams.team_types.tenant_id', 'teams.team_types.organization_id', 'teams.team_types.id'], name='fk_teams_team_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_teams_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'team_lead_user_id'], ['users.tenant_id', 'users.id'], name='fk_teams_lead', ondelete='SET NULL (team_lead_user_id)'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'organization_id', 'id', name='uq_teams_tenant_org_id'),
    schema='teams',
    comment='Teams: an organization-owned tree of operational teams.'
    )
    op.create_index('ix_teams_department', 'teams', ['department_id'], unique=False, schema='teams', postgresql_where=sa.text('department_id IS NOT NULL'))
    op.create_index('ix_teams_lead', 'teams', ['team_lead_user_id'], unique=False, schema='teams', postgresql_where=sa.text('team_lead_user_id IS NOT NULL'))
    op.create_index('ix_teams_name_trgm', 'teams', ['team_name'], unique=False, schema='teams', postgresql_using='gin', postgresql_ops={'team_name': 'gin_trgm_ops'}, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_teams_parent', 'teams', ['parent_id'], unique=False, schema='teams', postgresql_where=sa.text('parent_id IS NOT NULL'))
    op.create_index('ix_teams_scope_lft_rgt', 'teams', ['tenant_id', 'organization_id', '_lft', '_rgt'], unique=False, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_teams_team_type', 'teams', ['team_type_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_teams_deleted_at'), 'teams', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_teams_status'), 'teams', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_teams_tenant_id'), 'teams', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_teams_uuid'), 'teams', ['uuid'], unique=True, schema='teams')
    op.create_index('ix_teams_tenant_org', 'teams', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index('uq_teams_code_live', 'teams', ['tenant_id', 'organization_id', 'team_code'], unique=True, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('user_roles',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('role_id', sa.BigInteger(), nullable=False),
    sa.Column('scope_type', sa.String(length=20), server_default=sa.text("'organization'"), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('team_id', sa.BigInteger(), nullable=True),
    sa.Column('include_descendants', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='Also applies to child organizations / departments / teams of the scope node'),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True, comment='NULL = until revoked; a grant that ends is history, not deleted'),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("(scope_type = 'tenant' AND organization_id IS NULL AND department_id IS NULL AND team_id IS NULL) OR (scope_type = 'organization' AND organization_id IS NOT NULL     AND department_id IS NULL AND team_id IS NULL) OR (scope_type = 'department' AND organization_id IS NOT NULL     AND department_id IS NOT NULL AND team_id IS NULL) OR (scope_type = 'team' AND organization_id IS NOT NULL     AND team_id IS NOT NULL AND department_id IS NULL)", name='chk_user_roles_scope_columns'),
    sa.CheckConstraint("scope_type IN ('tenant','organization','department','team')", name='chk_user_roles_scope_type'),
    sa.CheckConstraint("status IN ('active','revoked')", name='chk_user_roles_status'),
    sa.CheckConstraint('valid_to IS NULL OR valid_to > valid_from', name='chk_user_roles_window'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'department_id'], ['teams.departments.tenant_id', 'teams.departments.organization_id', 'teams.departments.id'], name='fk_user_roles_department', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'team_id'], ['teams.teams.tenant_id', 'teams.teams.organization_id', 'teams.teams.id'], name='fk_user_roles_team', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_user_roles_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'role_id'], ['roles.tenant_id', 'roles.id'], name='fk_user_roles_role', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_user_roles_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='rbac',
    comment='Contextual role grants: tenant / organization / department / team scope.'
    )
    op.create_index(op.f('ix_rbac_user_roles_deleted_at'), 'user_roles', ['deleted_at'], unique=False, schema='rbac')
    op.create_index(op.f('ix_rbac_user_roles_status'), 'user_roles', ['status'], unique=False, schema='rbac')
    op.create_index(op.f('ix_rbac_user_roles_tenant_id'), 'user_roles', ['tenant_id'], unique=False, schema='rbac')
    op.create_index(op.f('ix_rbac_user_roles_uuid'), 'user_roles', ['uuid'], unique=True, schema='rbac')
    op.create_index('ix_user_roles_role', 'user_roles', ['role_id'], unique=False, schema='rbac', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_user_roles_tenant_org', 'user_roles', ['tenant_id', 'organization_id'], unique=False, schema='rbac')
    op.create_index('ix_user_roles_user', 'user_roles', ['tenant_id', 'user_id'], unique=False, schema='rbac', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_user_roles_open', 'user_roles', ['tenant_id', 'user_id', 'role_id', 'scope_type', sa.literal_column('coalesce(organization_id, 0)'), sa.literal_column('coalesce(department_id, 0)'), sa.literal_column('coalesce(team_id, 0)')], unique=True, schema='rbac', postgresql_where=sa.text("deleted_at IS NULL AND status = 'active' AND valid_to IS NULL"))
    op.create_table('user_teams',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('team_id', sa.BigInteger(), nullable=False),
    sa.Column('team_role_id', sa.BigInteger(), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('valid_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('valid_until', sa.DateTime(timezone=True), nullable=True, comment='NULL = ongoing; leaving a team closes it'),
    sa.Column('approval_status', sa.String(length=20), server_default=sa.text("'approved'"), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by', sa.BigInteger(), nullable=True, comment='users.id (no FK: survives the user)'),
    sa.Column('approval_notes', sa.Text(), nullable=True),
    sa.Column('has_individual_targets', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('has_custom_incentives', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('individual_achievement_ratio', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("approval_status IN ('pending','approved','rejected','cancelled')", name='chk_user_teams_approval_status'),
    sa.CheckConstraint("status IN ('active','inactive','on_leave','transferred')", name='chk_user_teams_status'),
    sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from', name='chk_user_teams_window'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'team_id'], ['teams.teams.tenant_id', 'teams.teams.organization_id', 'teams.teams.id'], name='fk_user_teams_team', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id', 'team_role_id'], ['teams.team_roles.tenant_id', 'teams.team_roles.organization_id', 'teams.team_roles.id'], name='fk_user_teams_team_role', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_user_teams_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_user_teams_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='teams',
    comment='Team memberships (effective-dated, approval-gated).'
    )
    op.create_index(op.f('ix_teams_user_teams_deleted_at'), 'user_teams', ['deleted_at'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_user_teams_status'), 'user_teams', ['status'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_user_teams_tenant_id'), 'user_teams', ['tenant_id'], unique=False, schema='teams')
    op.create_index(op.f('ix_teams_user_teams_uuid'), 'user_teams', ['uuid'], unique=True, schema='teams')
    op.create_index('ix_user_teams_team', 'user_teams', ['team_id'], unique=False, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_user_teams_team_role', 'user_teams', ['team_role_id'], unique=False, schema='teams', postgresql_where=sa.text('team_role_id IS NOT NULL'))
    op.create_index('ix_user_teams_tenant_org', 'user_teams', ['tenant_id', 'organization_id'], unique=False, schema='teams')
    op.create_index('ix_user_teams_user', 'user_teams', ['tenant_id', 'user_id'], unique=False, schema='teams', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_user_teams_one_primary', 'user_teams', ['tenant_id', 'user_id'], unique=True, schema='teams', postgresql_where=sa.text("is_primary AND status = 'active' AND valid_until IS NULL AND deleted_at IS NULL"))
    op.create_index('uq_user_teams_open', 'user_teams', ['tenant_id', 'user_id', 'team_id', sa.literal_column('coalesce(team_role_id, 0)')], unique=True, schema='teams', postgresql_where=sa.text('valid_until IS NULL AND deleted_at IS NULL'))
    op.add_column('employment_records', sa.Column('department_id', sa.BigInteger(), nullable=True, comment='teams.departments of THIS organization (composite FK)'))
    op.add_column('employment_records', sa.Column('job_title_id', sa.BigInteger(), nullable=True, comment='teams.job_titles of THIS organization (composite FK)'))
    op.alter_column('employment_records', 'department',
               existing_type=sa.VARCHAR(length=100),
               comment='LEGACY free text — superseded by department_id (teams.departments)',
               existing_nullable=True)
    op.alter_column('employment_records', 'designation',
               existing_type=sa.VARCHAR(length=100),
               comment='LEGACY free text — superseded by job_title_id (teams.job_titles)',
               existing_nullable=True)
    op.create_index('ix_employment_records_department', 'employment_records', ['department_id'], unique=False, postgresql_where=sa.text('department_id IS NOT NULL'))
    op.create_index('ix_employment_records_manager', 'employment_records', ['reporting_manager_user_id'], unique=False, postgresql_where=sa.text('reporting_manager_user_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_foreign_key('fk_employment_records_job_title', 'employment_records', 'job_titles', ['tenant_id', 'organization_id', 'job_title_id'], ['tenant_id', 'organization_id', 'id'], referent_schema='teams', ondelete='RESTRICT')
    op.create_foreign_key('fk_employment_records_department', 'employment_records', 'departments', ['tenant_id', 'organization_id', 'department_id'], ['tenant_id', 'organization_id', 'id'], referent_schema='teams', ondelete='RESTRICT')
    op.create_check_constraint('chk_employment_not_self_manager', 'employment_records', 'reporting_manager_user_id IS NULL OR reporting_manager_user_id <> user_id')

    # ── geo: departments and teams may own an address ───────────────────────────
    op.drop_constraint('chk_place_link_owner_type', 'place_links', type_='check', schema='geo')
    op.create_check_constraint('chk_place_link_owner_type', 'place_links', f"owner_type IN ({_in(_OWNER_TYPES)})", schema='geo')

    # ── the shared entity-type registry ─────────────────────────────────────────
    op.execute("""
        INSERT INTO core.entity_types (code, name, target_schema, target_table, created_by_name)
        VALUES ('department', 'Department', 'teams', 'departments', 'system:migration'),
               ('team', 'Team', 'teams', 'teams', 'system:migration')
        ON CONFLICT (code) DO NOTHING
    """)

    # ── data: the catalogue, then every organization's roles ───────────────────
    bind = op.get_bind()
    seed_permissions(bind)
    _seed_role_templates(bind)
    _backfill_legacy_permissions(bind)
    _backfill_default_roles(bind)
    _backfill_tenant_owners(bind)
    op.drop_column('roles', 'permissions')


def _seed_role_templates(bind) -> None:
    """Every organization gets every system role; explicit templates get their permissions (missing-only)."""
    for t in ROLE_TEMPLATES:
        bind.execute(sa.text("""
            INSERT INTO roles (tenant_id, organization_id, code, name, description, is_system, grant_mode,
                               hierarchy_level, created_by_name)
            SELECT o.tenant_id, o.id, CAST(:code AS varchar), CAST(:name AS varchar), CAST(:description AS text),
                   true, CAST(:mode AS varchar), CAST(:level AS integer), 'system:migration'
            FROM org_management.organizations o
            WHERE o.deleted_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM roles r WHERE r.organization_id = o.id
                              AND r.code = CAST(:code AS varchar) AND r.deleted_at IS NULL)
        """), {"code": t.code, "name": t.name, "description": t.description, "mode": t.grant_mode.value,
               "level": t.level})
        bind.execute(sa.text("""
            UPDATE roles SET grant_mode = :mode, hierarchy_level = :level
            WHERE code = :code AND is_system AND deleted_at IS NULL
        """), {"code": t.code, "mode": t.grant_mode.value, "level": t.level})
        if t.permissions:
            bind.execute(sa.text("""
                INSERT INTO rbac.role_permissions (tenant_id, organization_id, role_id, permission_id, created_by_name)
                SELECT r.tenant_id, r.organization_id, r.id, p.id, 'system:migration'
                FROM roles r
                JOIN rbac.permissions p ON p.permission_code = ANY(CAST(:codes AS varchar[]))
                WHERE r.code = CAST(:code AS varchar) AND r.is_system AND r.deleted_at IS NULL
                ON CONFLICT (role_id, permission_id) DO NOTHING
            """), {"code": t.code, "codes": sorted(t.permissions)})


def _backfill_legacy_permissions(bind) -> None:
    """Custom roles' free-text permission strings → catalogue rows; the raw list is kept regardless."""
    bind.execute(sa.text("""
        UPDATE roles SET app_metadata = app_metadata || jsonb_build_object('legacy_permissions', permissions)
        WHERE NOT is_system AND jsonb_typeof(permissions) = 'array' AND jsonb_array_length(permissions) > 0
    """))
    bind.execute(sa.text("""
        INSERT INTO rbac.role_permissions (tenant_id, organization_id, role_id, permission_id, created_by_name)
        SELECT r.tenant_id, r.organization_id, r.id, p.id, 'system:migration'
        FROM roles r
        CROSS JOIN LATERAL jsonb_array_elements_text(r.permissions) AS legacy(code)
        JOIN rbac.permissions p ON p.permission_code = legacy.code
        WHERE NOT r.is_system AND jsonb_typeof(r.permissions) = 'array' AND legacy.code = ANY(CAST(:known AS text[]))
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """), {"known": sorted(ALL_CODES)})


def _backfill_default_roles(bind) -> None:
    """A user with no role becomes ``member`` of their own organization (the composite FK requires it)."""
    bind.execute(sa.text("""
        UPDATE users SET role_id = r.id
        FROM roles r
        WHERE users.role_id IS NULL AND users.deleted_at IS NULL
          AND r.tenant_id = users.tenant_id AND r.organization_id = users.organization_id
          AND r.code = 'member' AND r.deleted_at IS NULL
    """))


def _backfill_tenant_owners(bind) -> None:
    """Owners of a ROOT organization also hold the tenant-wide owner grant (the tenant administrators)."""
    bind.execute(sa.text("""
        INSERT INTO rbac.user_roles (tenant_id, user_id, role_id, scope_type, organization_id,
                                     include_descendants, reason, created_by_name)
        SELECT u.tenant_id, u.id, u.role_id, 'tenant', NULL, true, 'migration: root-organization owner',
               'system:migration'
        FROM users u
        JOIN roles r ON r.id = u.role_id AND r.code = 'owner' AND r.is_system AND r.deleted_at IS NULL
        JOIN org_management.organizations o ON o.id = r.organization_id AND o.parent_id IS NULL
        WHERE u.deleted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM rbac.user_roles ur WHERE ur.user_id = u.id AND ur.role_id = u.role_id
                          AND ur.scope_type = 'tenant' AND ur.status = 'active' AND ur.deleted_at IS NULL
                          AND ur.valid_to IS NULL)
    """))


def downgrade() -> None:
    op.add_column('roles', sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False, comment='Permission strings (RBAC, enforced outside this schema)'))
    op.execute("DELETE FROM core.entity_types WHERE code IN ('department', 'team') AND created_by_name = 'system:migration'")
    op.drop_constraint('chk_place_link_owner_type', 'place_links', type_='check', schema='geo')
    op.create_check_constraint('chk_place_link_owner_type', 'place_links', f"owner_type IN ({_in(_OLD_OWNER_TYPES)})", schema='geo')

    op.drop_constraint('fk_employment_records_department', 'employment_records', type_='foreignkey')
    op.drop_constraint('fk_employment_records_job_title', 'employment_records', type_='foreignkey')
    op.drop_constraint('chk_employment_not_self_manager', 'employment_records', type_='check')
    op.drop_index('ix_employment_records_manager', table_name='employment_records')
    op.drop_index('ix_employment_records_department', table_name='employment_records')
    op.drop_column('employment_records', 'job_title_id')
    op.drop_column('employment_records', 'department_id')
    op.alter_column('employment_records', 'designation', existing_type=sa.VARCHAR(length=100), comment=None, existing_nullable=True)
    op.alter_column('employment_records', 'department', existing_type=sa.VARCHAR(length=100), comment=None, existing_nullable=True)

    op.drop_table('user_teams', schema='teams')
    op.drop_table('user_roles', schema='rbac')
    op.drop_table('teams', schema='teams')
    op.drop_table('job_titles', schema='teams')
    op.drop_table('departments', schema='teams')
    op.drop_table('team_roles', schema='teams')
    op.drop_table('role_permissions', schema='rbac')
    op.drop_table('team_types', schema='teams')
    op.drop_table('permissions', schema='rbac')

    op.drop_constraint('chk_roles_hierarchy_level', 'roles', type_='check')
    op.drop_constraint('chk_roles_grant_mode', 'roles', type_='check')
    op.drop_constraint('chk_roles_status', 'roles', type_='check')
    op.create_check_constraint('chk_roles_status', 'roles', "status IN ('active','inactive')")
    op.drop_constraint('uq_roles_tenant_id', 'roles', type_='unique')
    op.alter_column('roles', 'is_system', existing_type=sa.BOOLEAN(),
                    comment='Seeded role — cannot be deleted or re-coded',
                    existing_comment='Seeded role — cannot be deleted or re-coded; its permission set is code-owned',
                    existing_nullable=False, existing_server_default=sa.text('false'))
    op.drop_column('roles', 'is_assignable')
    op.drop_column('roles', 'hierarchy_level')
    op.drop_column('roles', 'grant_mode')
    op.execute("DROP SCHEMA IF EXISTS teams")
    op.execute("DROP SCHEMA IF EXISTS rbac")
