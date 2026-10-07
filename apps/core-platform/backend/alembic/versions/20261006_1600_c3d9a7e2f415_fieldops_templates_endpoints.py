"""Field operations — shift templates, route endpoints, scheduled shifts, the hub of the day,
richer telemetry (docs/fieldops/shift-templates.md, docs/fieldops/android-contract.md).

* ``fieldops.shift_templates`` — what a shift looks like when nobody scheduled one; assigned through
  the policy setting ``shift.template`` (no targeting columns of its own).
* ``user_hub_assignments`` — the user's hub by date (daily changes, NULL = explicitly none), one per
  user per day (``user_hub_assignments_no_overlap``; btree_gist is already installed by geo).
* ``fieldops.shifts`` — ``shift_code``, ``title``, ``work_type``, ``source``, template link + snapshot,
  route endpoints (start/end: anywhere / hub / assigned_hub / place, with optional enforcement), the
  frozen hub, end check, ``auto_close_at``; status ``missed``. ``auto_close_at`` is BACKFILLED for
  open shifts with the previous formula so the auto-close query (which keys on it) never strands one.
* ``fieldops.location_pings`` — geofence event, app state, battery state, client hints; geofence
  labels (CHECKs on the partitioned parent apply to every partition).
* ``fieldops.visits`` — ``stop_code``, ``external_ref`` (stops are planned visits).
* CHECK vocabularies regenerated: shift status / end reasons, anomaly types, checkpoint labels.
* Permissions: catalogue rows (``fieldops.shift:create``, ``fieldops.visit:create``,
  ``fieldops.shift_template:*``, ``hubs.assignment:*``, ``users.session:*``) and the planning grants
  on existing ``team_manager`` / ``department_head`` system roles.

Revision ID: c3d9a7e2f415
Revises: b7e4c1a9d3f2
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d9a7e2f415"
down_revision: str | None = "b7e4c1a9d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLANNING = ("fieldops.shift:create", "fieldops.shift:update", "fieldops.visit:create", "fieldops.visit:update",
             "fieldops.shift_template:read", "hubs.assignment:read", "hubs.assignment:manage")
_ROLE_GRANTS = {"team_manager": _PLANNING, "department_head": _PLANNING}

_SHIFT_STATUS_OLD = "status IN ('scheduled', 'active', 'paused', 'completed', 'auto_closed', 'cancelled')"
_SHIFT_STATUS_NEW = "status IN ('scheduled', 'active', 'paused', 'completed', 'auto_closed', 'cancelled', 'missed')"
_END_REASON_OLD = ("end_reason IS NULL OR end_reason IN ('user', 'auto_closed', 'superseded', 'cancelled', "
                   "'manager_correction')")
_END_REASON_NEW = ("end_reason IS NULL OR end_reason IN ('user', 'auto_closed', 'superseded', 'cancelled', "
                   "'manager_correction', 'policy_violation', 'consent_withdrawn')")
_LABEL_OLD = ("checkpoint_label IS NULL OR checkpoint_label IN ('shift_start', 'shift_end', 'shift_pause', "
              "'shift_resume', 'visit_start', 'visit_end', 'task_submitted', 'sos')")
_LABEL_NEW = ("checkpoint_label IS NULL OR checkpoint_label IN ('shift_start', 'shift_end', 'shift_pause', "
              "'shift_resume', 'visit_start', 'visit_end', 'task_submitted', 'sos', 'geofence_enter', 'geofence_exit')")
_ANOMALY_BASE = ("'ghost_shift', 'auto_closed', 'superseded_shift', 'long_gap', 'long_pause', 'too_many_pauses', "
                 "'low_tracking_coverage', 'tracking_disabled', 'mock_location', 'impossible_speed', 'clock_skew', "
                 "'clock_tampered', 'foreign_device', 'outside_geofence', 'justified_outside', "
                 "'hard_block_bypassed_offline', 'manual_location', 'short_visit', 'visit_without_shift', 'late_task', "
                 "'early_start', 'late_end', 'disputed_place', 'place_geotag_proposal'")
_ANOMALY_OLD = f"anomaly_type IN ({_ANOMALY_BASE})"
_ANOMALY_NEW = (f"anomaly_type IN ({_ANOMALY_BASE}, 'late_start', 'missed_shift', 'no_hub_assigned', "
                "'template_exceeds_max_hours', 'tracking_silent', 'device_handover', 'foreign_user_ping', "
                "'outside_start_place', 'outside_end_place')")

_SHIFT_CHECKS = [
    ("chk_shifts_end_check",
     "end_check IN ('inside', 'outside', 'uncertain', 'no_fix', 'not_configured', 'not_applicable')"),
    ("chk_shifts_work_type", "work_type IS NULL OR work_type IN ('delivery', 'collection', 'return', 'exchange', 'other')"),
    ("chk_shifts_source", "source IN ('scheduled', 'template', 'ad_hoc')"),
    ("chk_shifts_scheduled_window", "status <> 'scheduled' OR (planned_start_at IS NOT NULL AND planned_end_at IS NOT NULL "
                                    "AND planned_end_at > planned_start_at)"),
    ('chk_shifts_start_mode', "start_mode IN ('anywhere', 'hub', 'assigned_hub', 'place')"),
    ('chk_shifts_start_enforcement', "start_enforcement IS NULL OR start_enforcement IN ('advisory', 'soft_block', 'hard_block')"),
    ('chk_shifts_start_radius', 'start_radius_m IS NULL OR start_radius_m > 0'),
    ('chk_shifts_start_hub', "start_mode <> 'hub' OR start_hub_id IS NOT NULL"),
    ('chk_shifts_start_place', "start_mode <> 'place' OR start_place_id IS NOT NULL"),
    ('chk_shifts_start_anywhere', "start_mode <> 'anywhere' OR (start_hub_id IS NULL AND start_place_id IS NULL AND start_enforcement IS NULL AND start_radius_m IS NULL)"),
    ('chk_shifts_end_mode', "end_mode IN ('anywhere', 'hub', 'assigned_hub', 'place')"),
    ('chk_shifts_end_enforcement', "end_enforcement IS NULL OR end_enforcement IN ('advisory', 'soft_block', 'hard_block')"),
    ('chk_shifts_end_radius', 'end_radius_m IS NULL OR end_radius_m > 0'),
    ('chk_shifts_end_hub', "end_mode <> 'hub' OR end_hub_id IS NOT NULL"),
    ('chk_shifts_end_place', "end_mode <> 'place' OR end_place_id IS NOT NULL"),
    ('chk_shifts_end_anywhere', "end_mode <> 'anywhere' OR (end_hub_id IS NULL AND end_place_id IS NULL AND end_enforcement IS NULL AND end_radius_m IS NULL)"),
]
_PING_CHECKS = [
    ("chk_location_pings_geofence_label",
     "checkpoint_label NOT IN ('geofence_enter','geofence_exit') OR geofence_uuid IS NOT NULL"),
    ("chk_location_pings_app_state", "app_state IS NULL OR app_state IN ('foreground', 'background')"),
    ("chk_location_pings_battery_state",
     "battery_state IS NULL OR battery_state IN ('charging', 'discharging', 'full', 'not_charging', 'unknown')"),
]


_POLICY_ID_COMMENT = ("work_policies.id resolved at start (no FK)", "Most specific policy_layers.id at start (no FK)")
_START_CHECK_COMMENT = ("Start-place check (policy.require_start_at_place_id)",
                        "Start-place check (the resolved start endpoint)")


def _comments(*, new: bool) -> None:
    """Column comments that changed meaning with policy layers and route endpoints."""
    old_i, new_i = (0, 1) if new else (1, 0)
    op.alter_column("shifts", "policy_id", existing_type=sa.BigInteger(), existing_nullable=True,
                    comment=_POLICY_ID_COMMENT[new_i], existing_comment=_POLICY_ID_COMMENT[old_i], schema="fieldops")
    op.alter_column("shifts", "start_check", existing_type=sa.String(length=20), existing_nullable=False,
                    existing_server_default=sa.text("'not_configured'"), comment=_START_CHECK_COMMENT[new_i],
                    existing_comment=_START_CHECK_COMMENT[old_i], schema="fieldops")


def _swap(name: str, table: str, sql: str) -> None:
    op.drop_constraint(name, table, schema="fieldops", type_="check")
    op.create_check_constraint(name, table, sql, schema="fieldops")


def upgrade() -> None:
    op.create_table('shift_templates',
    sa.Column('code', sa.String(length=40), nullable=False, comment='Unique per tenant, e.g. WORK_SHIFT'),
    sa.Column('name', sa.String(length=120), nullable=False, comment="e.g. 'Work Shift' — the shift's title"),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('title_pattern', sa.String(length=200), nullable=True, comment='Optional title, with {name} {date} {weekday} placeholders'),
    sa.Column('work_type', sa.String(length=20), server_default=sa.text("'other'"), nullable=False),
    sa.Column('start_local_time', sa.Time(), nullable=False),
    sa.Column('end_local_time', sa.Time(), nullable=False),
    sa.Column('end_day_offset', sa.SmallInteger(), server_default=sa.text('0'), nullable=False, comment='1 = ends the next day (overnight)'),
    sa.Column('timezone', sa.String(length=64), nullable=True, comment="IANA zone; NULL = the organization's"),
    sa.Column('days_of_week', postgresql.ARRAY(sa.SmallInteger()), server_default=sa.text('ARRAY[1,2,3,4,5,6,7]::smallint[]'), nullable=False, comment='ISO weekdays (1 = Monday)'),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_until', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=10), server_default=sa.text("'active'"), nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('start_mode', sa.String(length=16), server_default=sa.text("'anywhere'"), nullable=False, comment='anywhere | hub | assigned_hub | place'),
    sa.Column('start_hub_id', sa.Integer(), nullable=True, comment='hubs.id (mode hub)'),
    sa.Column('start_place_id', sa.BigInteger(), nullable=True, comment='geo.places.id (mode place; resolved place for hub)'),
    sa.Column('start_enforcement', sa.String(length=20), nullable=True, comment='NULL = record only'),
    sa.Column('start_radius_m', sa.Integer(), nullable=True, comment='NULL = the fence, else the policy radius'),
    sa.Column('end_mode', sa.String(length=16), server_default=sa.text("'anywhere'"), nullable=False),
    sa.Column('end_hub_id', sa.Integer(), nullable=True),
    sa.Column('end_place_id', sa.BigInteger(), nullable=True),
    sa.Column('end_enforcement', sa.String(length=20), nullable=True),
    sa.Column('end_radius_m', sa.Integer(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("end_enforcement IS NULL OR end_enforcement IN ('advisory', 'soft_block', 'hard_block')", name='chk_shift_templates_end_enforcement'),
    sa.CheckConstraint("end_mode <> 'anywhere' OR (end_hub_id IS NULL AND end_place_id IS NULL AND end_enforcement IS NULL AND end_radius_m IS NULL)", name='chk_shift_templates_end_anywhere'),
    sa.CheckConstraint("end_mode <> 'hub' OR end_hub_id IS NOT NULL", name='chk_shift_templates_end_hub'),
    sa.CheckConstraint("end_mode <> 'place' OR end_place_id IS NOT NULL", name='chk_shift_templates_end_place'),
    sa.CheckConstraint("end_mode IN ('anywhere', 'hub', 'assigned_hub', 'place')", name='chk_shift_templates_end_mode'),
    sa.CheckConstraint("start_enforcement IS NULL OR start_enforcement IN ('advisory', 'soft_block', 'hard_block')", name='chk_shift_templates_start_enforcement'),
    sa.CheckConstraint("start_mode <> 'anywhere' OR (start_hub_id IS NULL AND start_place_id IS NULL AND start_enforcement IS NULL AND start_radius_m IS NULL)", name='chk_shift_templates_start_anywhere'),
    sa.CheckConstraint("start_mode <> 'hub' OR start_hub_id IS NOT NULL", name='chk_shift_templates_start_hub'),
    sa.CheckConstraint("start_mode <> 'place' OR start_place_id IS NOT NULL", name='chk_shift_templates_start_place'),
    sa.CheckConstraint("start_mode IN ('anywhere', 'hub', 'assigned_hub', 'place')", name='chk_shift_templates_start_mode'),
    sa.CheckConstraint("status IN ('active','inactive')", name='chk_shift_templates_status'),
    sa.CheckConstraint("work_type IN ('delivery', 'collection', 'return', 'exchange', 'other')", name='chk_shift_templates_work_type'),
    sa.CheckConstraint('cardinality(days_of_week) > 0 AND days_of_week <@ ARRAY[1,2,3,4,5,6,7]::smallint[]', name='chk_shift_templates_days'),
    sa.CheckConstraint('end_day_offset = 1 OR end_local_time > start_local_time', name='chk_shift_templates_window'),
    sa.CheckConstraint('end_day_offset IN (0, 1)', name='chk_shift_templates_day_offset'),
    sa.CheckConstraint('end_radius_m IS NULL OR end_radius_m > 0', name='chk_shift_templates_end_radius'),
    sa.CheckConstraint('start_radius_m IS NULL OR start_radius_m > 0', name='chk_shift_templates_start_radius'),
    sa.CheckConstraint('valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from', name='chk_shift_templates_validity'),
    sa.ForeignKeyConstraint(['tenant_id', 'end_hub_id'], ['hubs.tenant_id', 'hubs.id'], name='fk_shift_templates_end_hub', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'end_place_id'], ['geo.places.tenant_id', 'geo.places.id'], name='fk_shift_templates_end_place', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_shift_templates_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'start_hub_id'], ['hubs.tenant_id', 'hubs.id'], name='fk_shift_templates_start_hub', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'start_place_id'], ['geo.places.tenant_id', 'geo.places.id'], name='fk_shift_templates_start_place', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_shift_templates_tenant_id'),
    schema='fieldops',
    comment='Shift patterns used when no shift was scheduled; assigned via policy setting shift.template.'
    )
    op.create_index(op.f('ix_fieldops_shift_templates_deleted_at'), 'shift_templates', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_templates_tenant_id'), 'shift_templates', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_templates_uuid'), 'shift_templates', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_shift_templates_tenant_org', 'shift_templates', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_shift_templates_code_live', 'shift_templates', ['tenant_id', 'code'], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('user_hub_assignments',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('hub_id', sa.Integer(), nullable=True, comment='NULL = explicitly no hub for these days'),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_to', sa.Date(), nullable=True, comment='Inclusive; NULL = open-ended'),
    sa.Column('source', sa.String(length=16), server_default=sa.text("'manager'"), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
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
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    comment='Date-effective hub of a user (daily changes; NULL hub = explicitly none).'
    )
    op.create_index(op.f('ix_user_hub_assignments_deleted_at'), 'user_hub_assignments', ['deleted_at'], unique=False)
    op.create_index('ix_user_hub_assignments_hub_day', 'user_hub_assignments', ['tenant_id', 'hub_id', 'valid_from'], unique=False, postgresql_where=sa.text('deleted_at IS NULL AND hub_id IS NOT NULL'))
    op.create_index(op.f('ix_user_hub_assignments_status'), 'user_hub_assignments', ['status'], unique=False)
    op.create_index(op.f('ix_user_hub_assignments_tenant_id'), 'user_hub_assignments', ['tenant_id'], unique=False)
    op.create_index('ix_user_hub_assignments_tenant_org', 'user_hub_assignments', ['tenant_id', 'organization_id'], unique=False)
    op.create_index('ix_user_hub_assignments_user', 'user_hub_assignments', ['tenant_id', 'user_id', sa.literal_column('valid_from DESC')], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_user_hub_assignments_uuid'), 'user_hub_assignments', ['uuid'], unique=True)
    op.create_check_constraint("chk_user_hub_assignments_window", "user_hub_assignments",
                               "valid_to IS NULL OR valid_to >= valid_from")
    op.create_check_constraint("chk_user_hub_assignments_source", "user_hub_assignments",
                               "source IN ('manager','roster','hr_default')")
    op.create_foreign_key("fk_user_hub_assignments_user", "user_hub_assignments", "users",
                          ["tenant_id", "user_id"], ["tenant_id", "id"], ondelete="CASCADE")
    op.create_foreign_key("fk_user_hub_assignments_hub", "user_hub_assignments", "hubs",
                          ["tenant_id", "hub_id"], ["tenant_id", "id"], ondelete="CASCADE")
    op.create_foreign_key("fk_user_hub_assignments_tenant_org", "user_hub_assignments", "organizations",
                          ["tenant_id", "organization_id"], ["tenant_id", "id"], referent_schema="org_management",
                          ondelete="CASCADE")
    op.execute("ALTER TABLE user_hub_assignments ADD CONSTRAINT user_hub_assignments_no_overlap EXCLUDE USING gist "
               "(tenant_id WITH =, user_id WITH =, daterange(valid_from, valid_to, '[]') WITH &&) "
               "WHERE (deleted_at IS NULL)")

    op.add_column('location_pings', sa.Column('geofence_id', sa.BigInteger(), nullable=True, comment='geo.geofences.id the event names (no FK)'), schema='fieldops')
    op.add_column('location_pings', sa.Column('geofence_uuid', sa.UUID(), nullable=True, comment='Fence the client reported (enter/exit)'), schema='fieldops')
    op.add_column('location_pings', sa.Column('app_state', sa.String(length=12), nullable=True, comment='foreground | background'), schema='fieldops')
    op.add_column('location_pings', sa.Column('battery_state', sa.String(length=14), nullable=True), schema='fieldops')
    op.add_column('location_pings', sa.Column('client_significant', sa.Boolean(), nullable=True, comment='Client hint; diagnostics only'), schema='fieldops')
    op.add_column('location_pings', sa.Column('client_distance_m', sa.REAL(), nullable=True, comment='Client-computed hop; diagnostics only'), schema='fieldops')
    op.add_column('shifts', sa.Column('shift_code', sa.String(length=32), nullable=True, comment='Human reference SH-YYYYMMDD-NNNN (per tenant)'), schema='fieldops')
    op.add_column('shifts', sa.Column('title', sa.String(length=200), nullable=True), schema='fieldops')
    op.add_column('shifts', sa.Column('work_type', sa.String(length=20), nullable=True, comment='delivery | collection | return | exchange | other'), schema='fieldops')
    op.add_column('shifts', sa.Column('source', sa.String(length=12), server_default=sa.text("'ad_hoc'"), nullable=False, comment='scheduled | template | ad_hoc'), schema='fieldops')
    op.add_column('shifts', sa.Column('template_id', sa.BigInteger(), nullable=True, comment='fieldops.shift_templates.id it came from'), schema='fieldops')
    op.add_column('shifts', sa.Column('template_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="The template's values when used"), schema='fieldops')
    op.add_column('shifts', sa.Column('hub_id', sa.Integer(), nullable=True, comment="The user's hub for shift_date, frozen"), schema='fieldops')
    op.add_column('shifts', sa.Column('assigned_by', sa.BigInteger(), nullable=True, comment='users.id who scheduled it'), schema='fieldops')
    op.add_column('shifts', sa.Column('auto_close_at', sa.DateTime(timezone=True), nullable=True, comment='min(planned end + overtime, start + max hours) + grace — when auto-close will end it'), schema='fieldops')
    op.add_column('shifts', sa.Column('start_distance_m', sa.Numeric(precision=10, scale=1), nullable=True, comment='Headline of the start check'), schema='fieldops')
    op.add_column('shifts', sa.Column('end_check', sa.String(length=20), server_default=sa.text("'not_configured'"), nullable=False, comment='End-place check (never blocks)'), schema='fieldops')
    op.add_column('shifts', sa.Column('end_distance_m', sa.Numeric(precision=10, scale=1), nullable=True), schema='fieldops')
    op.add_column('shifts', sa.Column('start_mode', sa.String(length=16), server_default=sa.text("'anywhere'"), nullable=False, comment='anywhere | hub | assigned_hub | place'), schema='fieldops')
    op.add_column('shifts', sa.Column('start_hub_id', sa.Integer(), nullable=True, comment='hubs.id (mode hub)'), schema='fieldops')
    op.add_column('shifts', sa.Column('start_place_id', sa.BigInteger(), nullable=True, comment='geo.places.id (mode place; resolved place for hub)'), schema='fieldops')
    op.add_column('shifts', sa.Column('start_enforcement', sa.String(length=20), nullable=True, comment='NULL = record only'), schema='fieldops')
    op.add_column('shifts', sa.Column('start_radius_m', sa.Integer(), nullable=True, comment='NULL = the fence, else the policy radius'), schema='fieldops')
    op.add_column('shifts', sa.Column('end_mode', sa.String(length=16), server_default=sa.text("'anywhere'"), nullable=False), schema='fieldops')
    op.add_column('shifts', sa.Column('end_hub_id', sa.Integer(), nullable=True), schema='fieldops')
    op.add_column('shifts', sa.Column('end_place_id', sa.BigInteger(), nullable=True), schema='fieldops')
    op.add_column('shifts', sa.Column('end_enforcement', sa.String(length=20), nullable=True), schema='fieldops')
    op.add_column('shifts', sa.Column('end_radius_m', sa.Integer(), nullable=True), schema='fieldops')
    op.create_index('ix_shifts_auto_close', 'shifts', ['auto_close_at'], unique=False, schema='fieldops', postgresql_where=sa.text("status IN ('active','paused') AND deleted_at IS NULL"))
    op.create_index('ix_shifts_hub_date', 'shifts', ['tenant_id', 'hub_id', 'shift_date'], unique=False, schema='fieldops', postgresql_where=sa.text('hub_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_index('ix_shifts_scheduled', 'shifts', ['tenant_id', 'user_id', 'planned_start_at'], unique=False, schema='fieldops', postgresql_where=sa.text("status = 'scheduled' AND deleted_at IS NULL"))
    op.create_index('uq_shifts_code_live', 'shifts', ['tenant_id', 'shift_code'], unique=True, schema='fieldops', postgresql_where=sa.text('shift_code IS NOT NULL AND deleted_at IS NULL'))
    op.create_foreign_key('fk_shifts_start_place', 'shifts', 'places', ['tenant_id', 'start_place_id'], ['tenant_id', 'id'], source_schema='fieldops', referent_schema='geo', ondelete='RESTRICT')
    op.create_foreign_key('fk_shifts_start_hub', 'shifts', 'hubs', ['tenant_id', 'start_hub_id'], ['tenant_id', 'id'], source_schema='fieldops', ondelete='RESTRICT')
    op.create_foreign_key('fk_shifts_end_place', 'shifts', 'places', ['tenant_id', 'end_place_id'], ['tenant_id', 'id'], source_schema='fieldops', referent_schema='geo', ondelete='RESTRICT')
    op.create_foreign_key('fk_shifts_template', 'shifts', 'shift_templates', ['tenant_id', 'template_id'], ['tenant_id', 'id'], source_schema='fieldops', referent_schema='fieldops', ondelete='RESTRICT')
    op.create_foreign_key('fk_shifts_end_hub', 'shifts', 'hubs', ['tenant_id', 'end_hub_id'], ['tenant_id', 'id'], source_schema='fieldops', ondelete='RESTRICT')
    op.create_foreign_key('fk_shifts_hub', 'shifts', 'hubs', ['tenant_id', 'hub_id'], ['tenant_id', 'id'], source_schema='fieldops', ondelete='RESTRICT')
    op.add_column('visits', sa.Column('stop_code', sa.String(length=40), nullable=True, comment='Human stop reference (invoice / package no.)'), schema='fieldops')
    op.add_column('visits', sa.Column('external_ref', sa.String(length=100), nullable=True, comment='Order / shipment id in the owning module'), schema='fieldops')

    _comments(new=True)

    for name, sql in _SHIFT_CHECKS:
        op.create_check_constraint(name, "shifts", sql, schema="fieldops")
    for name, sql in _PING_CHECKS:
        op.create_check_constraint(name, "location_pings", sql, schema="fieldops")
    _swap("chk_shifts_status", "shifts", _SHIFT_STATUS_NEW)
    _swap("chk_shifts_end_reason", "shifts", _END_REASON_NEW)
    _swap("chk_location_pings_label", "location_pings", _LABEL_NEW)
    _swap("chk_anomalies_type", "anomalies", _ANOMALY_NEW)

    # Open shifts get their cap now: the auto-close query keys on auto_close_at (previous formula).
    op.execute("""
        UPDATE fieldops.shifts SET auto_close_at =
               COALESCE(planned_end_at,
                        started_at + COALESCE((policy_snapshot->>'max_shift_hours')::numeric, 12) * interval '1 hour')
             + COALESCE((policy_snapshot->>'auto_close_grace_minutes')::int, 60) * interval '1 minute'
         WHERE status IN ('active','paused') AND started_at IS NOT NULL
    """)

    bind = op.get_bind()
    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)
    for role_code, codes in _ROLE_GRANTS.items():
        bind.execute(sa.text("""
            INSERT INTO rbac.role_permissions (tenant_id, organization_id, role_id, permission_id,
                                               created_by_name, app_metadata, created_at, updated_at)
            SELECT r.tenant_id, r.organization_id, r.id, p.id, 'system:migration:fieldops-planning', '{}'::jsonb,
                   now(), now()
              FROM roles r
              JOIN rbac.permissions p ON p.permission_code = ANY(:codes)
             WHERE r.code = :role AND r.is_system AND r.grant_mode = 'explicit' AND r.deleted_at IS NULL
            ON CONFLICT (role_id, permission_id) DO NOTHING
        """), {"role": role_code, "codes": list(codes)})


def downgrade() -> None:
    op.execute("DELETE FROM rbac.role_permissions WHERE created_by_name = 'system:migration:fieldops-planning'")
    op.execute("UPDATE fieldops.shifts SET status = 'cancelled' WHERE status = 'missed'")
    op.execute("UPDATE fieldops.shifts SET end_reason = 'auto_closed' "
               "WHERE end_reason IN ('policy_violation', 'consent_withdrawn')")
    op.execute("DELETE FROM fieldops.anomalies WHERE anomaly_type IN ('late_start', 'missed_shift', 'no_hub_assigned', "
               "'template_exceeds_max_hours', 'tracking_silent', 'device_handover', 'foreign_user_ping', "
               "'outside_start_place', 'outside_end_place')")
    op.execute("UPDATE fieldops.location_pings SET checkpoint_label = NULL, kind = 'continuous' "
               "WHERE checkpoint_label IN ('geofence_enter', 'geofence_exit')")
    _comments(new=False)
    _swap("chk_anomalies_type", "anomalies", _ANOMALY_OLD)
    _swap("chk_location_pings_label", "location_pings", _LABEL_OLD)
    _swap("chk_shifts_end_reason", "shifts", _END_REASON_OLD)
    _swap("chk_shifts_status", "shifts", _SHIFT_STATUS_OLD)
    for name, _ in _PING_CHECKS:
        op.drop_constraint(name, "location_pings", schema="fieldops", type_="check")
    for name, _ in _SHIFT_CHECKS:
        op.drop_constraint(name, "shifts", schema="fieldops", type_="check")
    for name in ("fk_shifts_start_place", "fk_shifts_start_hub", "fk_shifts_end_place", "fk_shifts_end_hub",
                 "fk_shifts_template", "fk_shifts_hub"):
        op.drop_constraint(name, "shifts", schema="fieldops", type_="foreignkey")
    for name in ("ix_shifts_auto_close", "ix_shifts_hub_date", "ix_shifts_scheduled", "uq_shifts_code_live"):
        op.drop_index(name, table_name="shifts", schema="fieldops")
    for column in ("shift_code", "title", "work_type", "source", "template_id", "template_snapshot", "hub_id",
                   "assigned_by", "auto_close_at", "start_distance_m", "end_check", "end_distance_m", "start_mode",
                   "start_hub_id", "start_place_id", "start_enforcement", "start_radius_m", "end_mode", "end_hub_id",
                   "end_place_id", "end_enforcement", "end_radius_m"):
        op.drop_column("shifts", column, schema="fieldops")
    for column in ("geofence_id", "geofence_uuid", "app_state", "battery_state", "client_significant",
                   "client_distance_m"):
        op.drop_column("location_pings", column, schema="fieldops")
    op.drop_column("visits", "external_ref", schema="fieldops")
    op.drop_column("visits", "stop_code", schema="fieldops")
    op.drop_table("user_hub_assignments")
    op.drop_table("shift_templates", schema="fieldops")
