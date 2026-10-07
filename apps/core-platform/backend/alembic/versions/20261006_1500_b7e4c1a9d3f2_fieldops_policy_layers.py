"""Field operations — policy layers replace work policies.

``fieldops.work_policies`` (one whole row per organization × role; the most specific row won ALL
values) becomes ``fieldops.policy_layers``: sparse settings with a target (organization / role /
team / hub / beat / user), merged per setting field over the code defaults, with locks
(docs/fieldops/policy-layers.md). ``fieldops.policy_epochs`` holds the per-tenant config version.

Data: every live work-policy row is copied as ONE layer carrying ALL of its values — an organization
layer for ``role_id IS NULL``, a role layer otherwise. Copying every value (not only non-defaults)
reproduces the old winner-takes-all result exactly; admins can trim layers afterwards to gain
inheritance. Shifts keep their ``policy_snapshot`` (same flat names). ``work_policies`` is dropped.

Downgrade recreates ``work_policies`` from the organization/role layers (values a layer does not set
take the old column defaults) and STASHES each layer's exact settings, locks and priority in the row's
``app_metadata.policy_layer`` — so downgrade → upgrade restores those layers losslessly (settings with no
work_policies column, e.g. ``shift.template`` / ``session.field``, survive). Team/hub/user layers have no
home there and are lost on downgrade.

``policy_epochs`` is seeded with a TIME floor (minutes since 2020-01-01) and ``resolver.bump_epoch`` keeps
``epoch = GREATEST(epoch + 1, floor)`` — the app's ``config_version`` never decreases, even when the table is
dropped and recreated by a downgrade/upgrade.

Revision ID: b7e4c1a9d3f2
Revises: 5d8c2e1f7a90
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b7e4c1a9d3f2"
down_revision: str | None = "5d8c2e1f7a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT = (
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('created_by', sa.BigInteger(), nullable=True, comment='users.id of the creator (NULL = system)'),
    sa.Column('created_by_name', sa.String(length=255), nullable=True, comment='Creator display name at the time'),
    sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='users.id of the last updater'),
    sa.Column('updated_by_name', sa.String(length=255), nullable=True, comment='Last updater display name at the time'),
)
_TAIL = (
    sa.Column('is_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('row_version', sa.Integer(), server_default=sa.text('1'), nullable=False, comment='Optimistic-lock counter (incremented on every update)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
)

# Every work_policies column → its setting (field names are the flat policy names, unchanged).
_TO_LAYER_SQL = """
INSERT INTO fieldops.policy_layers
    (tenant_id, organization_id, name, description, scope_type, scope_id, settings, locked_keys, priority, status,
     created_by, created_by_name, updated_by, updated_by_name, created_at, updated_at, app_metadata)
SELECT p.tenant_id, p.organization_id, p.name, p.description,
       CASE WHEN p.role_id IS NULL THEN 'organization' ELSE 'role' END, p.role_id,
       -- a row written by this migration's downgrade carries the layer it came from: restore it exactly
       COALESCE(p.app_metadata->'policy_layer'->'settings', jsonb_build_object(
         'shift.requirements', jsonb_build_object(
             'requires_shift', p.requires_shift, 'allow_visits_without_shift', p.allow_visits_without_shift,
             'require_start_selfie', p.require_start_selfie, 'require_odometer', p.require_odometer),
         'shift.window', jsonb_build_object(
             'earliest_start_local', p.earliest_start_local::text, 'latest_end_local', p.latest_end_local::text,
             'max_shift_hours', p.max_shift_hours::float8, 'auto_close_grace_minutes', p.auto_close_grace_minutes,
             'stale_shift_after_minutes', p.stale_shift_after_minutes),
         'shift.start_place', to_jsonb(p.require_start_at_place_id),
         'pause.rules', jsonb_build_object(
             'max_pause_minutes', p.max_pause_minutes, 'max_pauses_per_shift', p.max_pauses_per_shift,
             'paid_pause_types', to_jsonb(p.paid_pause_types), 'track_during_pause', p.track_during_pause),
         'consent.required', to_jsonb(p.require_location_consent),
         'tracking.mode', to_jsonb(p.tracking_mode),
         'tracking.intervals', jsonb_build_object(
             'ping_interval_s', p.ping_interval_s, 'stationary_interval_s', p.stationary_interval_s,
             'ping_min_distance_m', p.ping_min_distance_m,
             'min_interval_s', LEAST(15, p.ping_interval_s, p.stationary_interval_s),
             'max_interval_s', GREATEST(600, p.ping_interval_s, p.stationary_interval_s)),
         'tracking.accuracy', jsonb_build_object('max_fix_accuracy_m', p.max_fix_accuracy_m),
         'geofence.rules', jsonb_build_object(
             'geofence_enforcement', p.geofence_enforcement, 'default_visit_radius_m', p.default_visit_radius_m,
             'geocoded_radius_factor', p.geocoded_radius_factor::float8,
             'allow_manual_location', p.allow_manual_location),
         'anomaly.thresholds', jsonb_build_object(
             'min_visit_minutes', p.min_visit_minutes::float8, 'late_task_window_hours', p.late_task_window_hours,
             'gap_flag_minutes', p.gap_flag_minutes, 'clock_skew_flag_seconds', p.clock_skew_flag_seconds,
             'min_tracking_coverage_pct', p.min_tracking_coverage_pct::float8)
       )),
       COALESCE(ARRAY(SELECT jsonb_array_elements_text(p.app_metadata->'policy_layer'->'locked_keys')),
                '{}'::text[]),
       COALESCE((p.app_metadata->'policy_layer'->>'priority')::smallint, 0),
       p.status, p.created_by, p.created_by_name, p.updated_by, p.updated_by_name, p.created_at, p.updated_at,
       jsonb_build_object('migrated_from_work_policy', p.id)
  FROM fieldops.work_policies p
 WHERE p.deleted_at IS NULL
"""


def upgrade() -> None:
    op.create_table('policy_epochs',
    sa.Column('epoch', sa.BigInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_policy_epochs_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_policy_epochs_tenant'),
    schema='fieldops',
    comment='Per-tenant policy version (bumped on layer writes).'
    )
    op.create_index(op.f('ix_fieldops_policy_epochs_tenant_id'), 'policy_epochs', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index('ix_policy_epochs_tenant_org', 'policy_epochs', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_table('policy_layers',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('scope_type', sa.String(length=20), nullable=False),
    sa.Column('scope_id', sa.BigInteger(), nullable=True, comment='Target id (roles/teams/hubs/beats/users); NULL for an organization layer. No FK.'),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment='Sparse {setting_key: value}; group values hold only the fields this layer sets'),
    sa.Column('locked_keys', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False, comment='Setting keys (or key.field) narrower layers may not override'),
    sa.Column('priority', sa.SmallInteger(), server_default=sa.text('0'), nullable=False, comment='Tie-breaker between layers of the same rank and depth'),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=10), server_default=sa.text("'active'"), nullable=False),
    *_AUDIT,
    *_TAIL,
    sa.CheckConstraint("(scope_type = 'organization') = (scope_id IS NULL)", name='chk_policy_layers_scope_id'),
    sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name='chk_policy_layers_settings_object'),
    sa.CheckConstraint("scope_type IN ('organization', 'role', 'team', 'hub', 'beat', 'user')", name='chk_policy_layers_scope_type'),
    sa.CheckConstraint("status IN ('active','inactive')", name='chk_policy_layers_status'),
    sa.CheckConstraint('effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from', name='chk_policy_layers_window'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_policy_layers_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_policy_layers_tenant_id'),
    schema='fieldops',
    comment='Sparse policy layers (organization/role/team/hub/beat/user), merged per setting.'
    )
    op.create_index(op.f('ix_fieldops_policy_layers_deleted_at'), 'policy_layers', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_policy_layers_tenant_id'), 'policy_layers', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_policy_layers_uuid'), 'policy_layers', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_policy_layers_lookup', 'policy_layers', ['tenant_id', 'scope_type', 'scope_id'], unique=False, schema='fieldops', postgresql_where=sa.text("deleted_at IS NULL AND status = 'active'"))
    op.create_index('ix_policy_layers_tenant_org', 'policy_layers', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_policy_layers_target_live', 'policy_layers', ['tenant_id', 'organization_id', 'scope_type', sa.literal_column('COALESCE(scope_id, 0)'), sa.literal_column("COALESCE(effective_from, '-infinity'::timestamptz)")], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))

    bind = op.get_bind()
    before = bind.execute(sa.text("SELECT count(*) FROM fieldops.work_policies WHERE deleted_at IS NULL")).scalar()
    bind.execute(sa.text(_TO_LAYER_SQL))
    after = bind.execute(sa.text("SELECT count(*) FROM fieldops.policy_layers")).scalar()
    if before != after:                                     # row-count guard: never lose a policy silently
        raise RuntimeError(f"policy layer copy mismatch: {before} work policies, {after} layers")
    bind.execute(sa.text("""
        INSERT INTO fieldops.policy_epochs (tenant_id, organization_id, epoch)
        SELECT DISTINCT ON (o.tenant_id) o.tenant_id, o.id, floor(extract(epoch FROM now() - timestamptz '2020-01-01 00:00:00+00') / 60)::bigint
          FROM org_management.organizations o
         ORDER BY o.tenant_id, o.depth, o.id
        ON CONFLICT (tenant_id) DO NOTHING
    """))
    op.drop_table('work_policies', schema='fieldops')


def downgrade() -> None:
    op.create_table('work_policies',
    sa.Column('role_id', sa.BigInteger(), nullable=True, comment="roles.id this policy targets; NULL = the organization's default"),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('requires_shift', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='Visits and tracking need an open shift'),
    sa.Column('allow_visits_without_shift', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Ad-hoc visits outside a shift (managers)'),
    sa.Column('require_location_consent', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='DPDP: an active location_tracking consent is required before a shift starts'),
    sa.Column('require_start_selfie', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('require_odometer', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('require_start_at_place_id', sa.BigInteger(), nullable=True, comment='Place the day should start at (e.g. the hub) — checked, advisory'),
    sa.Column('earliest_start_local', sa.Time(), nullable=True, comment='Organization-local time; earlier → early_start anomaly'),
    sa.Column('latest_end_local', sa.Time(), nullable=True, comment='Organization-local time; later → late_end anomaly'),
    sa.Column('max_shift_hours', sa.Numeric(precision=4, scale=1), server_default=sa.text('12.0'), nullable=False, comment='Auto-close cap when a shift has no planned end'),
    sa.Column('auto_close_grace_minutes', sa.Integer(), server_default=sa.text('60'), nullable=False),
    sa.Column('stale_shift_after_minutes', sa.Integer(), server_default=sa.text('240'), nullable=False, comment='An open shift idle this long is superseded by a new start from the same device'),
    sa.Column('max_pause_minutes', sa.Integer(), server_default=sa.text('90'), nullable=False, comment='A longer pause raises long_pause'),
    sa.Column('max_pauses_per_shift', sa.Integer(), server_default=sa.text('6'), nullable=False),
    sa.Column('paid_pause_types', postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY['rest','meeting','training']::text[]"), nullable=False, comment='Pause types that stay paid time; every other type is deducted from paid_minutes'),
    sa.Column('track_during_pause', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='false = the app stops tracking while paused (purpose limitation)'),
    sa.Column('tracking_mode', sa.String(length=20), server_default=sa.text("'continuous'"), nullable=False),
    sa.Column('ping_interval_s', sa.Integer(), server_default=sa.text('60'), nullable=False),
    sa.Column('stationary_interval_s', sa.Integer(), server_default=sa.text('300'), nullable=False),
    sa.Column('ping_min_distance_m', sa.Integer(), server_default=sa.text('50'), nullable=False),
    sa.Column('geofence_enforcement', sa.String(length=20), server_default=sa.text("'advisory'"), nullable=False),
    sa.Column('default_visit_radius_m', sa.Integer(), server_default=sa.text('100'), nullable=False),
    sa.Column('geocoded_radius_factor', sa.Numeric(precision=4, scale=2), server_default=sa.text('2.50'), nullable=False, comment='Radius multiplier for places whose coordinates are geocoded_only'),
    sa.Column('max_fix_accuracy_m', sa.Integer(), server_default=sa.text('100'), nullable=False, comment='Fixes less accurate than this are never evidence'),
    sa.Column('allow_manual_location', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('min_visit_minutes', sa.Numeric(precision=5, scale=1), server_default=sa.text('2.0'), nullable=False),
    sa.Column('late_task_window_hours', sa.Integer(), server_default=sa.text('12'), nullable=False, comment='How long after a visit ends a task may still be submitted'),
    sa.Column('gap_flag_minutes', sa.Integer(), server_default=sa.text('30'), nullable=False),
    sa.Column('clock_skew_flag_seconds', sa.Integer(), server_default=sa.text('300'), nullable=False),
    sa.Column('min_tracking_coverage_pct', sa.Numeric(precision=5, scale=2), server_default=sa.text('70.00'), nullable=False),
    *_AUDIT,
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    *_TAIL,
    sa.CheckConstraint("geofence_enforcement IN ('advisory', 'soft_block', 'hard_block')", name='chk_work_policies_enforcement'),
    sa.CheckConstraint("status IN ('active','inactive')", name='chk_work_policies_status'),
    sa.CheckConstraint("tracking_mode IN ('off', 'checkpoints_only', 'continuous')", name='chk_work_policies_tracking_mode'),
    sa.CheckConstraint('ping_interval_s > 0 AND stationary_interval_s > 0 AND ping_min_distance_m >= 0 AND default_visit_radius_m > 0 AND geocoded_radius_factor >= 1 AND max_fix_accuracy_m > 0 AND max_shift_hours > 0 AND auto_close_grace_minutes >= 0 AND stale_shift_after_minutes > 0 AND max_pause_minutes > 0 AND max_pauses_per_shift > 0 AND late_task_window_hours >= 0 AND min_visit_minutes >= 0 AND gap_flag_minutes > 0 AND clock_skew_flag_seconds > 0 AND min_tracking_coverage_pct BETWEEN 0 AND 100', name='chk_work_policies_positive'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_work_policies_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'require_start_at_place_id'], ['geo.places.tenant_id', 'geo.places.id'], name='fk_work_policies_start_place', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'role_id'], ['roles.tenant_id', 'roles.id'], name='fk_work_policies_role', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_work_policies_tenant_id'),
    schema='fieldops',
    comment='Field-work obligations per organization (and optionally per role); frozen onto each shift.'
    )
    op.create_index(op.f('ix_fieldops_work_policies_deleted_at'), 'work_policies', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_work_policies_status'), 'work_policies', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_work_policies_tenant_id'), 'work_policies', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index('ix_work_policies_tenant_org', 'work_policies', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_work_policies_target_live', 'work_policies', ['tenant_id', 'organization_id', sa.literal_column('COALESCE(role_id, 0)')], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.execute("""
        INSERT INTO fieldops.work_policies (tenant_id, organization_id, role_id, name, description, status,
            app_metadata,
            requires_shift, allow_visits_without_shift, require_start_selfie, require_odometer, require_location_consent,
            require_start_at_place_id, earliest_start_local, latest_end_local, max_shift_hours, auto_close_grace_minutes,
            stale_shift_after_minutes, max_pause_minutes, max_pauses_per_shift, paid_pause_types, track_during_pause,
            tracking_mode, ping_interval_s, stationary_interval_s, ping_min_distance_m, geofence_enforcement,
            default_visit_radius_m, geocoded_radius_factor, max_fix_accuracy_m, allow_manual_location, min_visit_minutes,
            late_task_window_hours, gap_flag_minutes, clock_skew_flag_seconds, min_tracking_coverage_pct)
        SELECT DISTINCT ON (l.tenant_id, l.organization_id, COALESCE(l.scope_id, 0))
               l.tenant_id, l.organization_id, l.scope_id, l.name, l.description, l.status,
               jsonb_build_object('policy_layer', jsonb_build_object(
                   'settings', l.settings, 'locked_keys', to_jsonb(l.locked_keys), 'priority', l.priority,
                   'uuid', l.uuid)),
               COALESCE((s->'shift.requirements'->>'requires_shift')::bool, true),
               COALESCE((s->'shift.requirements'->>'allow_visits_without_shift')::bool, false),
               COALESCE((s->'shift.requirements'->>'require_start_selfie')::bool, false),
               COALESCE((s->'shift.requirements'->>'require_odometer')::bool, false),
               COALESCE((s->>'consent.required')::bool, true),
               (s->>'shift.start_place')::bigint,
               (s->'shift.window'->>'earliest_start_local')::time, (s->'shift.window'->>'latest_end_local')::time,
               COALESCE((s->'shift.window'->>'max_shift_hours')::numeric, 12.0),
               COALESCE((s->'shift.window'->>'auto_close_grace_minutes')::int, 60),
               COALESCE((s->'shift.window'->>'stale_shift_after_minutes')::int, 240),
               COALESCE((s->'pause.rules'->>'max_pause_minutes')::int, 90),
               COALESCE((s->'pause.rules'->>'max_pauses_per_shift')::int, 6),
               COALESCE(ARRAY(SELECT jsonb_array_elements_text(s->'pause.rules'->'paid_pause_types')),
                        ARRAY['rest','meeting','training']),
               COALESCE((s->'pause.rules'->>'track_during_pause')::bool, false),
               COALESCE(s->>'tracking.mode', 'continuous'),
               COALESCE((s->'tracking.intervals'->>'ping_interval_s')::int, 60),
               COALESCE((s->'tracking.intervals'->>'stationary_interval_s')::int, 300),
               COALESCE((s->'tracking.intervals'->>'ping_min_distance_m')::int, 50),
               COALESCE(s->'geofence.rules'->>'geofence_enforcement', 'advisory'),
               COALESCE((s->'geofence.rules'->>'default_visit_radius_m')::int, 100),
               COALESCE((s->'geofence.rules'->>'geocoded_radius_factor')::numeric, 2.5),
               COALESCE((s->'tracking.accuracy'->>'max_fix_accuracy_m')::int, 100),
               COALESCE((s->'geofence.rules'->>'allow_manual_location')::bool, true),
               COALESCE((s->'anomaly.thresholds'->>'min_visit_minutes')::numeric, 2.0),
               COALESCE((s->'anomaly.thresholds'->>'late_task_window_hours')::int, 12),
               COALESCE((s->'anomaly.thresholds'->>'gap_flag_minutes')::int, 30),
               COALESCE((s->'anomaly.thresholds'->>'clock_skew_flag_seconds')::int, 300),
               COALESCE((s->'anomaly.thresholds'->>'min_tracking_coverage_pct')::numeric, 70.0)
          FROM fieldops.policy_layers l, LATERAL (SELECT l.settings AS s) x
         WHERE l.deleted_at IS NULL AND l.scope_type IN ('organization', 'role')
         ORDER BY l.tenant_id, l.organization_id, COALESCE(l.scope_id, 0), l.effective_from NULLS FIRST
    """)
    op.drop_table('policy_layers', schema='fieldops')
    op.drop_table('policy_epochs', schema='fieldops')
