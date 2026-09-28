"""Field operations — schema ``fieldops`` (+ ``core.idempotency_keys``).

Shifts (with pauses), visits, participants, tasks, the location stream, its upload
envelopes, the verification ledger, state transitions, anomalies, derived shift metrics,
devices / sessions / tracking-health events, and work policies. Design:
docs/fieldops/implementation-of-shift-visits-system.md (rationale:
docs/fieldops/improvement-document.md).

Besides the tables this migration:

* adds ``geo.geofences.visit_enforcement`` — a per-fence override of the policy's
  enforcement mode (the only change to the ``geo`` schema);
* creates the stream's DEFAULT partition plus monthly partitions for every month of copied
  history, the current month and three ahead. Partitions are then maintained by the
  ``fieldops.maintain_partitions`` Celery task — pg_partman is deliberately not used, for
  the reason ``zoho/control/retention.py`` records: the scratch test image does not ship it;
* creates ``fieldops.v_ping_flags`` (the quality bitmask, expanded);
* TAKES OVER ``public.user_location_pings``: every row is copied into
  ``fieldops.location_pings`` (row-count guarded) and the old table is dropped. The users
  module's ``/me/location`` routes now live in fieldops and write the new stream;
* registers ``shift``, ``visit`` (commentable) and ``visit_task`` in ``core.entity_types``;
* seeds the new permissions and adds them to the existing SYSTEM roles of every
  organization (member: field work; team_manager / department_head: review + tracks);
* ensures the ``location_history`` retention rule exists (auto-purge OFF until decided).

Downgrade restores ``public.user_location_pings`` from the stream (lossy: the new columns
have no home there) and drops everything else.

Revision ID: 5d8c2e1f7a90
Revises: 8f3f9c0b6d65
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

from alembic import op
from app.modules.comments.registration import register_commentable_entity_type

revision: str = "5d8c2e1f7a90"
down_revision: str | None = "8f3f9c0b6d65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Permissions this migration adds to each organization's SYSTEM roles (frozen here on purpose:
#: rbac/templates.py grows over time, a migration must not).
_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "member": ("fieldops.field_work:use",),
    "team_manager": (
        "fieldops.shift:read", "fieldops.shift:approve", "fieldops.visit:read", "fieldops.visit:approve",
        "fieldops.anomaly:read", "fieldops.anomaly:approve", "users.location:read",
    ),
    "department_head": (
        "fieldops.shift:read", "fieldops.shift:approve", "fieldops.visit:read", "fieldops.visit:approve",
        "fieldops.anomaly:read", "fieldops.anomaly:approve", "fieldops.policy:read", "users.location:read",
    ),
}

_QUALITY_FLAGS = (
    (1, "low_accuracy"), (2, "mock"), (4, "impossible_speed"), (8, "clock_skew"), (16, "clock_tampered"),
    (32, "partition_key_clamped"), (64, "foreign_device"), (128, "out_of_order"), (256, "stale_replay"),
    (512, "duplicate_coordinates"), (1024, "during_pause"),
)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fieldops")
    op.execute("COMMENT ON SCHEMA fieldops IS 'Field operations: shifts, pauses, visits, tasks, the location stream "
               "and its verification, anomalies and metrics (docs/fieldops/).'")

    op.create_table('idempotency_keys',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('key', sa.UUID(), nullable=False, comment='Client-generated key (X-Idempotency-Key)'),
    sa.Column('route', sa.String(length=200), nullable=False, comment='METHOD + route template'),
    sa.Column('request_fingerprint', sa.String(length=64), nullable=False, comment='sha256(method + route + canonical body)'),
    sa.Column('state', sa.String(length=12), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=True),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('entity_type', sa.String(length=40), nullable=True),
    sa.Column('entity_uuid', sa.UUID(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('organization_id', sa.BigInteger(), nullable=True, comment='Owning organization within the tenant; NULL = tenant-wide'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Owning tenant (isolation key)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('in_flight','completed')", name='chk_idempotency_keys_state'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_idempotency_keys_tenant_org', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'user_id', 'key', name='uq_idempotency_keys_user_key'),
    schema='core',
    comment='Stored responses of client-keyed mutations (offline replay safety).'
    )
    op.create_index(op.f('ix_core_idempotency_keys_tenant_id'), 'idempotency_keys', ['tenant_id'], unique=False, schema='core')
    op.create_index(op.f('ix_core_idempotency_keys_uuid'), 'idempotency_keys', ['uuid'], unique=True, schema='core')
    op.create_index('ix_idempotency_keys_expires', 'idempotency_keys', ['expires_at'], unique=False, schema='core')
    op.create_index('ix_idempotency_keys_tenant_org', 'idempotency_keys', ['tenant_id', 'organization_id'], unique=False, schema='core')
    op.create_table('anomalies',
    sa.Column('anomaly_type', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'open'"), nullable=False),
    sa.Column('subject_type', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=True),
    sa.Column('shift_id', sa.BigInteger(), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('detector', sa.String(length=64), nullable=False, comment='system:fieldops-<detector>'),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=False),
    sa.Column('resolved_by', sa.BigInteger(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution_code', sa.String(length=40), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
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
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("anomaly_type IN ('ghost_shift', 'auto_closed', 'superseded_shift', 'long_gap', 'long_pause', 'too_many_pauses', 'low_tracking_coverage', 'tracking_disabled', 'mock_location', 'impossible_speed', 'clock_skew', 'clock_tampered', 'foreign_device', 'outside_geofence', 'justified_outside', 'hard_block_bypassed_offline', 'manual_location', 'short_visit', 'visit_without_shift', 'late_task', 'early_start', 'late_end', 'disputed_place', 'place_geotag_proposal')", name='chk_anomalies_type'),
    sa.CheckConstraint("severity IN ('info', 'warning', 'critical')", name='chk_anomalies_severity'),
    sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'dismissed')", name='chk_anomalies_status'),
    sa.CheckConstraint("subject_type IN ('shift', 'visit', 'visit_task', 'shift_pause', 'place', 'device')", name='chk_anomalies_subject'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_anomalies_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Things a manager must review; status = open/acknowledged/…'
    )
    op.create_index('ix_anomalies_queue', 'anomalies', ['tenant_id', 'organization_id', 'status', sa.literal_column('detected_at DESC')], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_anomalies_shift', 'anomalies', ['shift_id'], unique=False, schema='fieldops', postgresql_where=sa.text('shift_id IS NOT NULL'))
    op.create_index('ix_anomalies_subject', 'anomalies', ['subject_type', 'subject_id'], unique=False, schema='fieldops')
    op.create_index('ix_anomalies_tenant_org', 'anomalies', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_anomalies_deleted_at'), 'anomalies', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_anomalies_status'), 'anomalies', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_anomalies_tenant_id'), 'anomalies', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_anomalies_uuid'), 'anomalies', ['uuid'], unique=True, schema='fieldops')
    op.create_index('uq_anomalies_dedupe', 'anomalies', ['tenant_id', 'dedupe_key'], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('device_events',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('device_id', sa.BigInteger(), nullable=True),
    sa.Column('session_uuid', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True, comment='Device wall clock as reported (raw telemetry, untrusted)'),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, comment='Business time (fieldops clock.py)'),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('time_basis', sa.String(length=24), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint("event_type IN ('gps_disabled', 'gps_enabled', 'permission_changed', 'airplane_on', 'airplane_off', 'power_save_on', 'power_save_off', 'time_changed', 'timezone_changed', 'app_restarted_after_kill', 'boot', 'mock_app_detected', 'low_battery', 'tracking_paused', 'tracking_resumed')", name='chk_device_events_type'),
    sa.CheckConstraint("time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_device_events_time_basis'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_device_events_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Append-only tracking-health events (uuid = client event id).'
    )
    op.create_index('ix_device_events_tenant_org', 'device_events', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_device_events_user_time', 'device_events', ['tenant_id', 'user_id', sa.literal_column('occurred_at DESC')], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_device_events_tenant_id'), 'device_events', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_device_events_uuid'), 'device_events', ['uuid'], unique=True, schema='fieldops')
    op.create_table('location_checks',
    sa.Column('subject_type', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.BigInteger(), nullable=False),
    sa.Column('phase', sa.String(length=16), nullable=False),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('evaluator_version', sa.SmallInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False, comment="The instant being verified (the action's occurred_at)"),
    sa.Column('fix_uuid', sa.UUID(), nullable=True),
    sa.Column('fix_recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fix_accuracy_m', sa.REAL(), nullable=True),
    sa.Column('evidence_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('target_kind', sa.String(length=16), nullable=False),
    sa.Column('geofence_id', sa.BigInteger(), nullable=True),
    sa.Column('place_id', sa.BigInteger(), nullable=True),
    sa.Column('radius_m', sa.Double(), nullable=True),
    sa.Column('distance_m', sa.Double(), nullable=True, comment='0 when a polygon covers the fix'),
    sa.Column('result', sa.String(length=20), nullable=False),
    sa.Column('enforcement', sa.String(length=20), nullable=False),
    sa.Column('action_taken', sa.String(length=24), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint("action_taken IN ('recorded', 'justification_required', 'blocked', 'justified', 'bypassed_offline')", name='chk_location_checks_action'),
    sa.CheckConstraint("enforcement IN ('advisory', 'soft_block', 'hard_block')", name='chk_location_checks_enforcement'),
    sa.CheckConstraint("phase IN ('start', 'end', 'revalidation')", name='chk_location_checks_phase'),
    sa.CheckConstraint("result IN ('inside', 'outside', 'uncertain', 'no_fix', 'not_configured', 'not_applicable')", name='chk_location_checks_result'),
    sa.CheckConstraint("subject_type IN ('shift', 'visit', 'visit_task', 'shift_pause', 'place', 'device')", name='chk_location_checks_subject'),
    sa.CheckConstraint("target_kind IN ('polygon', 'circle', 'place_default', 'none')", name='chk_location_checks_target'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_location_checks_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Location/geofence verification ledger (append-only).'
    )
    op.create_index(op.f('ix_fieldops_location_checks_tenant_id'), 'location_checks', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_location_checks_uuid'), 'location_checks', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_location_checks_subject', 'location_checks', ['subject_type', 'subject_id', 'phase', sa.literal_column('evaluated_at DESC')], unique=False, schema='fieldops')
    op.create_index('ix_location_checks_tenant_org', 'location_checks', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_table('ping_batches',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('device_id', sa.BigInteger(), nullable=True),
    sa.Column('device_session_uuid', sa.UUID(), nullable=True),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True, comment='Device wall clock when the batch was SENT (X-Device-Sent-At)'),
    sa.Column('client_elapsed_ms', sa.BigInteger(), nullable=True, comment='Monotonic clock at send'),
    sa.Column('client_boot_count', sa.Integer(), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ingest_ms', sa.Integer(), nullable=True),
    sa.Column('item_count', sa.Integer(), nullable=False),
    sa.Column('accepted_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('duplicate_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('rejected_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False, comment='[{uuid, status, reason}] for NON-accepted items only'),
    sa.Column('payload_sha256', sa.String(length=64), nullable=True),
    sa.Column('raw_object_key', sa.Text(), nullable=True, comment='Archived raw body (object storage), if kept'),
    sa.Column('raw_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_ping_batches_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='One row per ping upload (uuid = client batch id): envelope, counts, non-accepted items.'
    )
    op.create_index(op.f('ix_fieldops_ping_batches_tenant_id'), 'ping_batches', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_ping_batches_uuid'), 'ping_batches', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_ping_batches_tenant_org', 'ping_batches', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_ping_batches_user_time', 'ping_batches', ['tenant_id', 'user_id', sa.literal_column('received_at DESC')], unique=False, schema='fieldops')
    op.create_table('state_transitions',
    sa.Column('subject_type', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.BigInteger(), nullable=False),
    sa.Column('subject_uuid', sa.UUID(), nullable=True),
    sa.Column('axis', sa.String(length=12), nullable=False),
    sa.Column('from_state', sa.String(length=20), nullable=True),
    sa.Column('to_state', sa.String(length=20), nullable=False),
    sa.Column('reason_code', sa.String(length=40), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('time_basis', sa.String(length=24), nullable=False),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True, comment='Device wall clock as reported (raw)'),
    sa.Column('actor_user_id', sa.BigInteger(), nullable=True),
    sa.Column('actor_label', sa.String(length=255), nullable=True, comment='Display name or system:<component>'),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('idempotency_key', sa.UUID(), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='{"field": [before, after]} for corrections'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint("axis IN ('lifecycle', 'review')", name='chk_state_transitions_axis'),
    sa.CheckConstraint("source IN ('device', 'server', 'system', 'manager')", name='chk_state_transitions_source'),
    sa.CheckConstraint("subject_type IN ('shift', 'visit', 'visit_task', 'shift_pause', 'place', 'device')", name='chk_state_transitions_subject'),
    sa.CheckConstraint("time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_state_transitions_time_basis'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_state_transitions_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Every lifecycle/review transition (append-only).'
    )
    op.create_index(op.f('ix_fieldops_state_transitions_tenant_id'), 'state_transitions', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_state_transitions_uuid'), 'state_transitions', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_state_transitions_subject', 'state_transitions', ['subject_type', 'subject_id', 'occurred_at'], unique=False, schema='fieldops')
    op.create_index('ix_state_transitions_tenant_org', 'state_transitions', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
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
    op.create_index(op.f('ix_fieldops_work_policies_uuid'), 'work_policies', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_work_policies_tenant_org', 'work_policies', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_work_policies_target_live', 'work_policies', ['tenant_id', 'organization_id', sa.literal_column('COALESCE(role_id, 0)')], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('devices',
    sa.Column('user_id', sa.BigInteger(), nullable=False, comment='The user the installation belongs to'),
    sa.Column('installation_id', sa.String(length=64), nullable=False, comment='App-generated installation id (opaque, preserved exactly)'),
    sa.Column('platform', sa.String(length=10), nullable=False),
    sa.Column('manufacturer', sa.String(length=100), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('os_version', sa.String(length=40), nullable=True),
    sa.Column('app_id', sa.String(length=100), nullable=True, comment='Package / bundle id (FieldMate vs DLP)'),
    sa.Column('push_token', sa.Text(), nullable=True),
    sa.Column('is_primary', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment="The user's field device"),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
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
    sa.Column('deactivation_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivation_reason', sa.Text(), nullable=True),
    sa.Column('deactivated_by', sa.BigInteger(), nullable=True, comment='users.id who deactivated it'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("platform IN ('android', 'ios', 'web')", name='chk_devices_platform'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_devices_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_devices_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_devices_tenant_id'),
    schema='fieldops',
    comment='App installations; a shift is bound to one (device binding).'
    )
    op.create_index('ix_devices_tenant_org', 'devices', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_devices_user', 'devices', ['tenant_id', 'user_id'], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_fieldops_devices_deleted_at'), 'devices', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_devices_status'), 'devices', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_devices_tenant_id'), 'devices', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_devices_uuid'), 'devices', ['uuid'], unique=True, schema='fieldops')
    op.create_index('uq_devices_installation_live', 'devices', ['tenant_id', 'installation_id'], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_devices_one_primary', 'devices', ['tenant_id', 'user_id'], unique=True, schema='fieldops', postgresql_where=sa.text('is_primary AND deleted_at IS NULL'))
    op.create_geospatial_table('location_pings',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, comment='PARTITION KEY: device fix time, clamped to [received-45d, received+10min]'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment="The CLIENT's id of the fix (UUIDv7) — the idempotency key"),
    sa.Column('batch_id', sa.BigInteger(), nullable=True, comment='fieldops.ping_batches.id (no FK)'),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('device_id', sa.BigInteger(), nullable=True, comment='fieldops.devices.id (no FK)'),
    sa.Column('device_session_uuid', sa.UUID(), nullable=True),
    sa.Column('shift_id', sa.BigInteger(), nullable=True, comment='No FK — back-filled by link_orphan_pings'),
    sa.Column('visit_id', sa.BigInteger(), nullable=True, comment='No FK — back-filled by link_orphan_pings'),
    sa.Column('shift_uuid', sa.UUID(), nullable=True),
    sa.Column('visit_uuid', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(length=12), server_default=sa.text("'continuous'"), nullable=False),
    sa.Column('checkpoint_label', sa.String(length=24), nullable=True),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True, comment='Device wall clock of the fix as reported — raw, unclamped, untrusted'),
    sa.Column('elapsed_realtime_ms', sa.BigInteger(), nullable=True, comment='Monotonic clock at the fix'),
    sa.Column('boot_count', sa.Integer(), nullable=True),
    sa.Column('sequence_no', sa.BigInteger(), nullable=True, comment='Per device session; gap/reorder diagnostics'),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, comment='BUSINESS time (clock.py)'),
    sa.Column('time_basis', sa.String(length=24), nullable=False),
    sa.Column('clock_skew_ms', sa.BigInteger(), nullable=True, comment='received_at - device sent_at'),
    sa.Column('coordinates', Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True, comment='WGS84 point; NULL for a checkpoint with no fix'),
    sa.Column('latitude', sa.Numeric(precision=10, scale=7), sa.Computed('ST_Y(coordinates::geometry)', persisted=True), nullable=True, comment='GENERATED'),
    sa.Column('longitude', sa.Numeric(precision=10, scale=7), sa.Computed('ST_X(coordinates::geometry)', persisted=True), nullable=True, comment='GENERATED'),
    sa.Column('accuracy_m', sa.REAL(), nullable=True, comment='Horizontal accuracy (68% radius)'),
    sa.Column('altitude_m', sa.REAL(), nullable=True),
    sa.Column('vertical_accuracy_m', sa.REAL(), nullable=True),
    sa.Column('heading_deg', sa.REAL(), nullable=True),
    sa.Column('heading_accuracy_deg', sa.REAL(), nullable=True),
    sa.Column('speed_mps', sa.REAL(), nullable=True),
    sa.Column('speed_accuracy_mps', sa.REAL(), nullable=True),
    sa.Column('provider', sa.String(length=10), server_default=sa.text("'gps'"), nullable=False),
    sa.Column('satellites', sa.SmallInteger(), nullable=True),
    sa.Column('is_mock', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('activity_type', sa.String(length=12), nullable=True),
    sa.Column('activity_confidence', sa.SmallInteger(), nullable=True),
    sa.Column('battery_pct', sa.SmallInteger(), nullable=True),
    sa.Column('is_charging', sa.Boolean(), nullable=True),
    sa.Column('power_save', sa.Boolean(), nullable=True),
    sa.Column('network_type', sa.String(length=10), nullable=True),
    sa.Column('quality_flags', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='Bitmask — enums.QualityFlag / fieldops.v_ping_flags'),
    sa.Column('manual_reason', sa.Text(), nullable=True),
    sa.Column('place_id', sa.BigInteger(), nullable=True, comment='Checkpoints: the resolved place'),
    sa.Column('geocode_call_id', sa.BigInteger(), nullable=True, comment='Checkpoints: geo.geocode_api_calls.id'),
    sa.Column('address_label', sa.Text(), nullable=True, comment='Checkpoints: display snapshot'),
    sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Sparse vendor fields; NULL normally'),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.CheckConstraint("activity_type IS NULL OR activity_type IN ('still', 'walking', 'running', 'on_bicycle', 'in_vehicle', 'unknown')", name='chk_location_pings_activity'),
    sa.CheckConstraint("checkpoint_label IS NULL OR checkpoint_label IN ('shift_start', 'shift_end', 'shift_pause', 'shift_resume', 'visit_start', 'visit_end', 'task_submitted', 'sos')", name='chk_location_pings_label'),
    sa.CheckConstraint("checkpoint_label IS NULL OR kind = 'checkpoint'", name='chk_location_pings_label_kind'),
    sa.CheckConstraint("checkpoint_label NOT IN ('shift_start','shift_end','shift_pause','shift_resume') OR shift_uuid IS NOT NULL", name='chk_location_pings_shift_label'),
    sa.CheckConstraint("checkpoint_label NOT IN ('visit_start','visit_end','task_submitted') OR visit_uuid IS NOT NULL", name='chk_location_pings_visit_label'),
    sa.CheckConstraint("kind IN ('continuous', 'checkpoint', 'manual')", name='chk_location_pings_kind'),
    sa.CheckConstraint("provider <> 'manual' OR manual_reason IS NOT NULL", name='chk_location_pings_manual_reason'),
    sa.CheckConstraint("provider IN ('gps', 'fused', 'network', 'passive', 'manual')", name='chk_location_pings_provider'),
    sa.CheckConstraint("time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_location_pings_time_basis'),
    sa.CheckConstraint('accuracy_m IS NULL OR accuracy_m >= 0', name='chk_location_pings_accuracy'),
    sa.CheckConstraint('activity_confidence IS NULL OR activity_confidence BETWEEN 0 AND 100', name='chk_location_pings_activity_confidence'),
    sa.CheckConstraint('battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100', name='chk_location_pings_battery'),
    sa.CheckConstraint('heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)', name='chk_location_pings_heading'),
    sa.CheckConstraint('speed_mps IS NULL OR speed_mps >= 0', name='chk_location_pings_speed'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_location_pings_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_location_pings_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('recorded_at', 'id', name='pk_location_pings'),
    sa.UniqueConstraint('tenant_id', 'user_id', 'uuid', 'recorded_at', name='uq_location_pings_client'),
    schema='fieldops',
    postgresql_partition_by='RANGE (recorded_at)'
    )
    op.create_index(op.f('ix_fieldops_location_pings_tenant_id'), 'location_pings', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index('ix_location_pings_checkpoint', 'location_pings', ['tenant_id', 'occurred_at'], unique=False, schema='fieldops', postgresql_where=sa.text("kind = 'checkpoint'"))
    op.create_index('ix_location_pings_shift', 'location_pings', ['shift_id', 'occurred_at'], unique=False, schema='fieldops', postgresql_where=sa.text('shift_id IS NOT NULL'))
    op.create_index('ix_location_pings_tenant_org', 'location_pings', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_location_pings_unlinked', 'location_pings', ['received_at'], unique=False, schema='fieldops', postgresql_where=sa.text('(shift_uuid IS NOT NULL AND shift_id IS NULL) OR (visit_uuid IS NOT NULL AND visit_id IS NULL)'))
    op.create_index('ix_location_pings_user_time', 'location_pings', ['tenant_id', 'user_id', sa.literal_column('occurred_at DESC')], unique=False, schema='fieldops')
    op.create_table('device_sessions',
    sa.Column('device_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('client_app_version', sa.String(length=32), nullable=True, comment='Field-app version (NOT app_version)'),
    sa.Column('client_build', sa.String(length=32), nullable=True),
    sa.Column('os_version', sa.String(length=40), nullable=True),
    sa.Column('sdk_int', sa.Integer(), nullable=True, comment='Android API level'),
    sa.Column('boot_count', sa.Integer(), nullable=True, comment='Device boot counter at session start'),
    sa.Column('location_permission', sa.String(length=24), nullable=True),
    sa.Column('precise_location', sa.Boolean(), nullable=True, comment='False = Android 12+ approximate grant'),
    sa.Column('battery_optimization_exempt', sa.Boolean(), nullable=True),
    sa.Column('power_save_mode', sa.Boolean(), nullable=True),
    sa.Column('auto_time_enabled', sa.Boolean(), nullable=True, comment='False = user-set clock (tamper signal)'),
    sa.Column('auto_timezone_enabled', sa.Boolean(), nullable=True),
    sa.Column('developer_options', sa.Boolean(), nullable=True),
    sa.Column('is_rooted', sa.Boolean(), nullable=True),
    sa.Column('integrity_verdict', sa.String(length=40), nullable=True, comment='Play Integrity / App Attest summary'),
    sa.Column('integrity_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('network_type', sa.String(length=10), nullable=True),
    sa.Column('carrier', sa.String(length=60), nullable=True),
    sa.Column('locale', sa.String(length=20), nullable=True),
    sa.Column('device_timezone', sa.String(length=64), nullable=True, comment='Diagnostics only — never business time'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("location_permission IS NULL OR location_permission IN ('always', 'while_in_use', 'denied')", name='chk_device_sessions_permission'),
    sa.ForeignKeyConstraint(['tenant_id', 'device_id'], ['fieldops.devices.tenant_id', 'fieldops.devices.id'], name='fk_device_sessions_device', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_device_sessions_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='One row per app session (uuid = client session id): the capability snapshot.'
    )
    op.create_index('ix_device_sessions_device', 'device_sessions', ['device_id', sa.literal_column('started_at DESC')], unique=False, schema='fieldops')
    op.create_index('ix_device_sessions_tenant_org', 'device_sessions', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_device_sessions_user', 'device_sessions', ['tenant_id', 'user_id', sa.literal_column('started_at DESC')], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_device_sessions_tenant_id'), 'device_sessions', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_device_sessions_uuid'), 'device_sessions', ['uuid'], unique=True, schema='fieldops')
    op.create_table('shifts',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('device_id', sa.BigInteger(), nullable=True, comment='The device the shift is bound to'),
    sa.Column('policy_id', sa.BigInteger(), nullable=True, comment='work_policies.id resolved at start (no FK)'),
    sa.Column('policy_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False, comment='The effective policy values frozen at start — old shifts are judged by the rules then in force'),
    sa.Column('shift_date', sa.Date(), nullable=False, comment="Business day of the start in the ORGANIZATION's timezone, frozen"),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'active'"), nullable=False),
    sa.Column('review_status', sa.String(length=20), server_default=sa.text("'not_required'"), nullable=False),
    sa.Column('planned_start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('planned_end_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True, comment='occurred_at of the start (clock.py)'),
    sa.Column('start_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('start_time_basis', sa.String(length=24), nullable=True),
    sa.Column('start_client_timestamp', sa.DateTime(timezone=True), nullable=True, comment='Device wall clock at the start, as reported (raw)'),
    sa.Column('start_check', sa.String(length=20), server_default=sa.text("'not_configured'"), nullable=False, comment='Start-place check (policy.require_start_at_place_id)'),
    sa.Column('start_manual_location_reason', sa.Text(), nullable=True),
    sa.Column('start_selfie_media_uuid', sa.UUID(), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_time_basis', sa.String(length=24), nullable=True),
    sa.Column('end_client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_by', sa.String(length=10), nullable=True),
    sa.Column('end_reason', sa.String(length=24), nullable=True),
    sa.Column('paused_since', sa.DateTime(timezone=True), nullable=True, comment="Start of the CURRENT pause; NULL unless status = 'paused'"),
    sa.Column('pause_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('pause_minutes', sa.Numeric(precision=8, scale=2), nullable=True, comment='All pause time, closed shifts'),
    sa.Column('unpaid_pause_minutes', sa.Numeric(precision=8, scale=2), nullable=True, comment='Pause time deducted from paid time'),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True, comment='Max occurred_at of any ping/visit/task/pause; Core UPDATE with GREATEST, no row_version bump'),
    sa.Column('wall_clock_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('paid_minutes', sa.Numeric(precision=8, scale=2), nullable=True, comment='Wall clock minus unpaid pauses — payroll'),
    sa.Column('duration_basis', sa.String(length=20), nullable=True),
    sa.Column('vehicle_id', sa.BigInteger(), nullable=True),
    sa.Column('travel_mode', sa.String(length=20), nullable=True),
    sa.Column('odometer_start_km', sa.Numeric(precision=10, scale=1), nullable=True),
    sa.Column('odometer_end_km', sa.Numeric(precision=10, scale=1), nullable=True),
    sa.Column('cancellation_reason', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True, comment='Current summary; the note stream is comments'),
    sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
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
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("(status = 'paused') = (paused_since IS NOT NULL)", name='chk_shifts_paused_since'),
    sa.CheckConstraint("duration_basis IS NULL OR duration_basis IN ('device_reported', 'system_estimated', 'manager_adjusted')", name='chk_shifts_duration_basis'),
    sa.CheckConstraint("end_reason IS NULL OR end_reason IN ('user', 'auto_closed', 'superseded', 'cancelled', 'manager_correction')", name='chk_shifts_end_reason'),
    sa.CheckConstraint("end_time_basis IS NULL OR end_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_shifts_end_time_basis'),
    sa.CheckConstraint("ended_by IS NULL OR ended_by IN ('user', 'system', 'manager')", name='chk_shifts_ended_by'),
    sa.CheckConstraint("review_status IN ('not_required', 'pending', 'approved', 'rejected', 'corrected')", name='chk_shifts_review_status'),
    sa.CheckConstraint("start_check IN ('inside', 'outside', 'uncertain', 'no_fix', 'not_configured', 'not_applicable')", name='chk_shifts_start_check'),
    sa.CheckConstraint("start_time_basis IS NULL OR start_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_shifts_start_time_basis'),
    sa.CheckConstraint("status IN ('scheduled', 'active', 'paused', 'completed', 'auto_closed', 'cancelled')", name='chk_shifts_status'),
    sa.CheckConstraint("status NOT IN ('active','paused') OR (started_at IS NOT NULL AND ended_at IS NULL)", name='chk_shifts_open_has_start'),
    sa.CheckConstraint("status NOT IN ('completed','auto_closed') OR ended_at IS NOT NULL", name='chk_shifts_closed_has_end'),
    sa.CheckConstraint("travel_mode IS NULL OR travel_mode IN ('two_wheeler', 'four_wheeler', 'public_transport', 'walk', 'company_vehicle', 'bicycle')", name='chk_shifts_travel_mode'),
    sa.CheckConstraint('ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at', name='chk_shifts_end_after_start'),
    sa.CheckConstraint('odometer_end_km IS NULL OR odometer_start_km IS NULL OR odometer_end_km >= odometer_start_km', name='chk_shifts_odometer'),
    sa.CheckConstraint('pause_count >= 0', name='chk_shifts_pause_count'),
    sa.ForeignKeyConstraint(['tenant_id', 'device_id'], ['fieldops.devices.tenant_id', 'fieldops.devices.id'], name='fk_shifts_device', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_shifts_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_shifts_user', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_shifts_tenant_id'),
    schema='fieldops',
    comment='Work sessions; at most one open (active|paused) per user.'
    )
    op.create_index(op.f('ix_fieldops_shifts_deleted_at'), 'shifts', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shifts_status'), 'shifts', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shifts_tenant_id'), 'shifts', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shifts_uuid'), 'shifts', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_shifts_open', 'shifts', ['last_activity_at'], unique=False, schema='fieldops', postgresql_where=sa.text("status IN ('active','paused') AND deleted_at IS NULL"))
    op.create_index('ix_shifts_org_date', 'shifts', ['tenant_id', 'organization_id', 'shift_date', 'status'], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_shifts_review', 'shifts', ['tenant_id', 'shift_date'], unique=False, schema='fieldops', postgresql_where=sa.text("review_status = 'pending' AND deleted_at IS NULL"))
    op.create_index('ix_shifts_tenant_org', 'shifts', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_shifts_user_date', 'shifts', ['tenant_id', 'user_id', sa.literal_column('shift_date DESC')], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_shifts_one_open', 'shifts', ['tenant_id', 'user_id'], unique=True, schema='fieldops', postgresql_where=sa.text("status IN ('active','paused') AND deleted_at IS NULL"))
    op.create_table('shift_metrics',
    sa.Column('shift_id', sa.BigInteger(), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('metrics_version', sa.Integer(), nullable=False),
    sa.Column('inputs_hash', sa.String(length=64), nullable=True, comment='Skip the write when inputs are unchanged'),
    sa.Column('wall_clock_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('pause_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('paid_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('engaged_minutes', sa.Numeric(precision=8, scale=2), nullable=True, comment='Visit time + travel between first and last visit — productivity, NOT payroll'),
    sa.Column('visit_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('travel_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('idle_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('first_visit_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_visit_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fix_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('accepted_fix_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('tracking_coverage_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('longest_gap_minutes', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('mock_fix_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('low_accuracy_fix_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('clock_skew_max_s', sa.Integer(), nullable=True),
    sa.Column('gps_distance_km', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('odometer_distance_km', sa.Numeric(precision=10, scale=1), nullable=True),
    sa.Column('visits_total', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_completed', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_cancelled', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_planned', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_unplanned', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('field_visits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('telephonic_visits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('video_visits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('productive_visits', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_checked', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_inside', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_outside', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('visits_uncertain', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('geofence_compliance_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('orders_field', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('orders_telephonic', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('order_value_field', sa.Numeric(precision=18, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('order_value_telephonic', sa.Numeric(precision=18, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('collections_value', sa.Numeric(precision=18, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('currency_code', sa.String(length=3), nullable=True, comment='NULL when no amount was recorded'),
    sa.Column('anomaly_count_open', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_shift_metrics_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'shift_id'], ['fieldops.shifts.tenant_id', 'fieldops.shifts.id'], name='fk_shift_metrics_shift', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('shift_id', name='uq_shift_metrics_shift'),
    schema='fieldops',
    comment='Derived KPIs per shift (recomputable; metrics_version).'
    )
    op.create_index(op.f('ix_fieldops_shift_metrics_tenant_id'), 'shift_metrics', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_metrics_uuid'), 'shift_metrics', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_shift_metrics_tenant_org', 'shift_metrics', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_table('shift_pauses',
    sa.Column('shift_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('pause_type', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('is_paid', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Frozen from policy.paid_pause_types at pause start'),
    sa.Column('tracking_suspended', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='True = the app was told to stop tracking during this pause (policy.track_during_pause false)'),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('start_received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('start_time_basis', sa.String(length=24), nullable=False),
    sa.Column('start_client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_time_basis', sa.String(length=24), nullable=True),
    sa.Column('end_client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_by', sa.String(length=10), nullable=True),
    sa.Column('end_reason', sa.String(length=20), nullable=True),
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
    sa.CheckConstraint("end_reason IS NULL OR end_reason IN ('resumed', 'shift_ended', 'auto_closed', 'manager')", name='chk_shift_pauses_end_reason'),
    sa.CheckConstraint("end_time_basis IS NULL OR end_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_shift_pauses_end_basis'),
    sa.CheckConstraint("ended_by IS NULL OR ended_by IN ('user', 'system', 'manager')", name='chk_shift_pauses_ended_by'),
    sa.CheckConstraint("pause_type IN ('meal', 'rest', 'prayer', 'personal', 'meeting', 'training', 'vehicle_issue', 'weather', 'network_issue', 'other')", name='chk_shift_pauses_type'),
    sa.CheckConstraint("start_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_shift_pauses_start_basis'),
    sa.CheckConstraint('(ended_at IS NULL) = (end_reason IS NULL)', name='chk_shift_pauses_end_reason_set'),
    sa.CheckConstraint('ended_at IS NULL OR ended_at >= started_at', name='chk_shift_pauses_end_after_start'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_shift_pauses_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'shift_id'], ['fieldops.shifts.tenant_id', 'fieldops.shifts.id'], name='fk_shift_pauses_shift', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Pauses of a shift (breaks, outages …); paid-ness frozen from policy.'
    )
    op.create_index(op.f('ix_fieldops_shift_pauses_deleted_at'), 'shift_pauses', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_pauses_status'), 'shift_pauses', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_pauses_tenant_id'), 'shift_pauses', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_shift_pauses_uuid'), 'shift_pauses', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_shift_pauses_shift', 'shift_pauses', ['shift_id', 'started_at'], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_shift_pauses_tenant_org', 'shift_pauses', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_shift_pauses_one_open', 'shift_pauses', ['tenant_id', 'shift_id'], unique=True, schema='fieldops', postgresql_where=sa.text('ended_at IS NULL AND deleted_at IS NULL'))
    op.create_table('visits',
    sa.Column('user_id', sa.BigInteger(), nullable=False, comment='The rep who owns the visit'),
    sa.Column('shift_id', sa.BigInteger(), nullable=True, comment='NULL only when the policy allows it'),
    sa.Column('device_id', sa.BigInteger(), nullable=True),
    sa.Column('channel', sa.String(length=12), server_default=sa.text("'field'"), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'in_progress'"), nullable=False),
    sa.Column('review_status', sa.String(length=20), server_default=sa.text("'not_required'"), nullable=False),
    sa.Column('source', sa.String(length=12), server_default=sa.text("'unplanned'"), nullable=False),
    sa.Column('plan_ref', sa.UUID(), nullable=True, comment='Beat/journey-plan item this fulfils (plans are a later module)'),
    sa.Column('sequence_in_plan', sa.Integer(), nullable=True),
    sa.Column('purpose', sa.String(length=24), server_default=sa.text("'sales_call'"), nullable=False),
    sa.Column('account_type', sa.String(length=64), nullable=True, comment='core.entity_types.code (customer, …)'),
    sa.Column('account_id', sa.BigInteger(), nullable=True, comment="Id in the account type's table"),
    sa.Column('place_id', sa.BigInteger(), nullable=True, comment='geo.places — where the visit happens'),
    sa.Column('contact_person_ref', sa.UUID(), nullable=True, comment='Who was met — reserved for the contacts module'),
    sa.Column('planned_start_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('planned_end_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('start_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('start_time_basis', sa.String(length=24), nullable=True),
    sa.Column('start_client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('end_time_basis', sa.String(length=24), nullable=True),
    sa.Column('end_client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('geofence_entry_at', sa.DateTime(timezone=True), nullable=True, comment='First fix of the first inside run lasting ≥ dwell (dwell detection)'),
    sa.Column('geofence_exit_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('visit_time_basis', sa.String(length=10), nullable=True, comment='button | geofence — which pair KPIs used'),
    sa.Column('start_check', sa.String(length=20), server_default=sa.text("'not_configured'"), nullable=False),
    sa.Column('end_check', sa.String(length=20), server_default=sa.text("'not_configured'"), nullable=False),
    sa.Column('distance_from_target_m', sa.Numeric(precision=10, scale=1), nullable=True),
    sa.Column('start_justification_code', sa.String(length=40), nullable=True),
    sa.Column('start_justification_note', sa.Text(), nullable=True),
    sa.Column('manual_location_reason', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(length=24), nullable=True),
    sa.Column('no_order_reason', sa.String(length=40), nullable=True),
    sa.Column('follow_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=40), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.BigInteger(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
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
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("cancellation_reason IS NULL OR cancellation_reason IN ('user', 'shift_auto_closed', 'superseded', 'manager', 'duplicate')", name='chk_visits_cancellation_reason'),
    sa.CheckConstraint("channel <> 'field' OR account_id IS NOT NULL OR place_id IS NOT NULL", name='chk_visits_field_is_somewhere'),
    sa.CheckConstraint("channel = 'field' OR (start_check = 'not_applicable' AND end_check = 'not_applicable')", name='chk_visits_remote_not_applicable'),
    sa.CheckConstraint("channel IN ('field', 'telephonic', 'video')", name='chk_visits_channel'),
    sa.CheckConstraint("end_check IN ('inside', 'outside', 'uncertain', 'no_fix', 'not_configured', 'not_applicable')", name='chk_visits_end_check'),
    sa.CheckConstraint("end_time_basis IS NULL OR end_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_visits_end_time_basis'),
    sa.CheckConstraint("no_order_reason IS NULL OR no_order_reason IN ('stock_sufficient', 'price_issue', 'credit_hold', 'competitor', 'not_interested', 'other')", name='chk_visits_no_order_reason'),
    sa.CheckConstraint("outcome IS NULL OR outcome IN ('order_taken', 'no_order', 'collection_only', 'delivered', 'closed_shop', 'owner_absent', 'follow_up', 'info_only')", name='chk_visits_outcome'),
    sa.CheckConstraint("purpose IN ('sales_call', 'collection', 'delivery', 'service', 'merchandising', 'survey', 'prospecting', 'relationship')", name='chk_visits_purpose'),
    sa.CheckConstraint("review_status IN ('not_required', 'pending', 'approved', 'rejected', 'corrected')", name='chk_visits_review_status'),
    sa.CheckConstraint("source IN ('planned', 'unplanned')", name='chk_visits_source'),
    sa.CheckConstraint("start_check IN ('inside', 'outside', 'uncertain', 'no_fix', 'not_configured', 'not_applicable')", name='chk_visits_start_check'),
    sa.CheckConstraint("start_justification_code IS NULL OR start_justification_code IN ('shop_relocated', 'met_outside', 'gps_poor', 'customer_location_wrong', 'other')", name='chk_visits_justification'),
    sa.CheckConstraint("start_time_basis IS NULL OR start_time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_visits_start_time_basis'),
    sa.CheckConstraint("status <> 'completed' OR (started_at IS NOT NULL AND ended_at IS NOT NULL)", name='chk_visits_completed_closed'),
    sa.CheckConstraint("status <> 'in_progress' OR (started_at IS NOT NULL AND ended_at IS NULL)", name='chk_visits_in_progress_open'),
    sa.CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'cancelled', 'missed')", name='chk_visits_status'),
    sa.CheckConstraint("visit_time_basis IS NULL OR visit_time_basis IN ('button','geofence')", name='chk_visits_visit_time_basis'),
    sa.CheckConstraint('(account_type IS NULL) = (account_id IS NULL)', name='chk_visits_account_pair'),
    sa.CheckConstraint('ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at', name='chk_visits_end_after_start'),
    sa.ForeignKeyConstraint(['account_type'], ['core.entity_types.code'], name='fk_visits_account_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_visits_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'place_id'], ['geo.places.tenant_id', 'geo.places.id'], name='fk_visits_place', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'shift_id'], ['fieldops.shifts.tenant_id', 'fieldops.shifts.id'], name='fk_visits_shift', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_visits_user', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_visits_tenant_id'),
    schema='fieldops',
    comment='Customer engagements; at most one in_progress per user.'
    )
    op.create_index(op.f('ix_fieldops_visits_deleted_at'), 'visits', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visits_status'), 'visits', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visits_tenant_id'), 'visits', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visits_uuid'), 'visits', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_visits_account', 'visits', ['tenant_id', 'account_type', 'account_id', sa.literal_column('started_at DESC')], unique=False, schema='fieldops', postgresql_where=sa.text('account_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_index('ix_visits_place', 'visits', ['place_id', sa.literal_column('started_at DESC')], unique=False, schema='fieldops', postgresql_where=sa.text('place_id IS NOT NULL AND deleted_at IS NULL'))
    op.create_index('ix_visits_plan', 'visits', ['plan_ref'], unique=False, schema='fieldops', postgresql_where=sa.text('plan_ref IS NOT NULL'))
    op.create_index('ix_visits_review', 'visits', ['tenant_id', 'started_at'], unique=False, schema='fieldops', postgresql_where=sa.text("review_status = 'pending' AND deleted_at IS NULL"))
    op.create_index('ix_visits_shift', 'visits', ['shift_id', 'started_at'], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_visits_tenant_org', 'visits', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_visits_user', 'visits', ['tenant_id', 'user_id', sa.literal_column('started_at DESC')], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('uq_visits_one_in_progress', 'visits', ['tenant_id', 'user_id'], unique=True, schema='fieldops', postgresql_where=sa.text("status = 'in_progress' AND deleted_at IS NULL"))
    op.create_table('visit_participants',
    sa.Column('visit_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('participant_role', sa.String(length=20), server_default=sa.text("'joint_working'"), nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
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
    sa.CheckConstraint("participant_role IN ('joint_working', 'trainee', 'observer', 'backup')", name='chk_visit_participants_role'),
    sa.CheckConstraint('left_at IS NULL OR left_at >= joined_at', name='chk_visit_participants_window'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_visit_participants_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_visit_participants_user', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'visit_id'], ['fieldops.visits.tenant_id', 'fieldops.visits.id'], name='fk_visit_participants_visit', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='Joint working: people who joined a visit they do not own.'
    )
    op.create_index(op.f('ix_fieldops_visit_participants_deleted_at'), 'visit_participants', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_participants_status'), 'visit_participants', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_participants_tenant_id'), 'visit_participants', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_participants_uuid'), 'visit_participants', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_visit_participants_tenant_org', 'visit_participants', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('uq_visit_participants_live', 'visit_participants', ['tenant_id', 'visit_id', 'user_id'], unique=True, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('visit_tasks',
    sa.Column('visit_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False, comment='Who performed it (may be a participant)'),
    sa.Column('task_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=12), server_default=sa.text("'submitted'"), nullable=False),
    sa.Column('performed_at', sa.DateTime(timezone=True), nullable=False, comment='occurred_at — independent of the visit window'),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('time_basis', sa.String(length=24), nullable=False),
    sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('after_visit_end', sa.Boolean(), server_default=sa.text('false'), nullable=False, comment='Performed after the visit ended — recorded, never rejected'),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('payload_version', sa.SmallInteger(), server_default=sa.text('1'), nullable=False),
    sa.Column('reference_type', sa.String(length=64), nullable=True, comment='core.entity_types.code of the document'),
    sa.Column('reference_id', sa.BigInteger(), nullable=True),
    sa.Column('reference_uuid', sa.UUID(), nullable=True, comment='Client uuid of a document created offline, until its module resolves it'),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('currency_code', sa.String(length=3), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
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
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.BigInteger(), nullable=True, comment='users.id who deleted it'),
    sa.Column('deleted_reason', sa.Text(), nullable=True, comment='Why it was deleted'),
    sa.CheckConstraint("currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'", name='chk_visit_tasks_currency'),
    sa.CheckConstraint("status <> 'voided' OR void_reason IS NOT NULL", name='chk_visit_tasks_void_reason'),
    sa.CheckConstraint("status IN ('submitted', 'voided')", name='chk_visit_tasks_status'),
    sa.CheckConstraint("task_type IN ('take_order', 'record_no_order', 'collect_payment', 'deliver', 'process_return', 'process_exchange', 'stock_check', 'product_detailing', 'distribute_sample', 'survey', 'merchandising', 'customer_feedback', 'note')", name='chk_visit_tasks_type'),
    sa.CheckConstraint("time_basis IN ('monotonic', 'wall_clock_corrected', 'device_wall_clock', 'server_receipt', 'manager')", name='chk_visit_tasks_time_basis'),
    sa.CheckConstraint('amount IS NULL OR currency_code IS NOT NULL', name='chk_visit_tasks_amount_currency'),
    sa.ForeignKeyConstraint(['reference_type'], ['core.entity_types.code'], name='fk_visit_tasks_reference_type', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_visit_tasks_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_visit_tasks_user', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'visit_id'], ['fieldops.visits.tenant_id', 'fieldops.visits.id'], name='fk_visit_tasks_visit', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='fieldops',
    comment='What was done in a visit (registry-validated payload).'
    )
    op.create_index(op.f('ix_fieldops_visit_tasks_deleted_at'), 'visit_tasks', ['deleted_at'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_tasks_status'), 'visit_tasks', ['status'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_tasks_tenant_id'), 'visit_tasks', ['tenant_id'], unique=False, schema='fieldops')
    op.create_index(op.f('ix_fieldops_visit_tasks_uuid'), 'visit_tasks', ['uuid'], unique=True, schema='fieldops')
    op.create_index('ix_visit_tasks_reference', 'visit_tasks', ['reference_type', 'reference_id'], unique=False, schema='fieldops', postgresql_where=sa.text('reference_id IS NOT NULL'))
    op.create_index('ix_visit_tasks_reference_uuid', 'visit_tasks', ['reference_uuid'], unique=False, schema='fieldops', postgresql_where=sa.text('reference_uuid IS NOT NULL AND reference_id IS NULL'))
    op.create_index('ix_visit_tasks_tenant_org', 'visit_tasks', ['tenant_id', 'organization_id'], unique=False, schema='fieldops')
    op.create_index('ix_visit_tasks_visit', 'visit_tasks', ['visit_id', 'task_type'], unique=False, schema='fieldops', postgresql_where=sa.text('deleted_at IS NULL'))

    # ── geo.geofences: per-fence override of the policy's enforcement mode ──────────────────
    op.add_column("geofences", sa.Column(
        "visit_enforcement", sa.String(length=20), nullable=True,
        comment="Per-fence override of the field-ops policy's geofence enforcement "
                "(advisory / soft_block / hard_block); NULL = follow the policy"), schema="geo")
    op.create_check_constraint(
        "chk_geofence_visit_enforcement", "geofences",
        "visit_enforcement IS NULL OR visit_enforcement IN ('advisory','soft_block','hard_block')", schema="geo")

    # ── the stream's partitions ─────────────────────────────────────────────────────────────
    # DEFAULT first: a partitioned parent with no partition rejects every INSERT (the lesson of
    # 3b7f0ae91c46). Then one partition per month of history being copied (bounded to a year back —
    # older rows stay in DEFAULT), the current month and three ahead. Names and bounds match
    # app/modules/fieldops/partitions.py, which maintains them from here on.
    op.execute("CREATE TABLE fieldops.location_pings_default PARTITION OF fieldops.location_pings DEFAULT")
    op.execute("COMMENT ON TABLE fieldops.location_pings_default IS 'Catch-all partition: fixes outside every "
               "monthly partition (clamped clocks, history older than the maintained window).'")
    op.execute("""
        DO $$
        DECLARE
            this_month date := date_trunc('month', now())::date;
            first_month date;
            m date;
        BEGIN
            IF to_regclass('public.user_location_pings') IS NOT NULL THEN
                SELECT date_trunc('month', min(recorded_at))::date INTO first_month
                  FROM public.user_location_pings
                 WHERE recorded_at >= this_month - interval '12 months'
                   AND recorded_at <= now() + interval '10 minutes';
            END IF;
            m := LEAST(COALESCE(first_month, this_month), this_month);
            WHILE m <= (this_month + interval '3 months')::date LOOP
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS fieldops.%I PARTITION OF fieldops.location_pings '
                    'FOR VALUES FROM (%L) TO (%L)',
                    'location_pings_p' || to_char(m, 'YYYYMM'),
                    (m::timestamp AT TIME ZONE 'UTC'),
                    ((m + interval '1 month')::timestamp AT TIME ZONE 'UTC'));
                m := (m + interval '1 month')::date;
            END LOOP;
        END $$;
    """)

    # ── fieldops.v_ping_flags: the quality bitmask, readable ────────────────────────────────
    flags = ", ".join(f"({bit}, '{name}')" for bit, name in _QUALITY_FLAGS)
    op.execute(f"""
        CREATE VIEW fieldops.v_ping_flags AS
        SELECT p.tenant_id, p.organization_id, p.user_id, p.recorded_at, p.id, p.uuid, p.occurred_at,
               p.shift_id, p.visit_id, p.quality_flags,
               ARRAY(SELECT f.name FROM (VALUES {flags}) AS f(bit, name)
                      WHERE p.quality_flags & f.bit <> 0 ORDER BY f.bit) AS flag_names
          FROM fieldops.location_pings p
         WHERE p.quality_flags <> 0
    """)
    op.execute("COMMENT ON VIEW fieldops.v_ping_flags IS 'Fixes with quality flags, bitmask expanded "
               "(app/modules/fieldops/enums.py QualityFlag). Analytics only: no tenant filter of its own.'")

    # ── take over public.user_location_pings ────────────────────────────────────────────────
    # Legacy rows have no client id (a fresh uuidv7), no send-time clocks (time basis
    # device_wall_clock, occurred_at = the device time capped at receipt), and a free-text device
    # id (kept in extras). Values the new CHECKs refuse are nulled rather than failing the copy.
    op.execute("""
        DO $$
        DECLARE
            before bigint;
            after bigint;
        BEGIN
            IF to_regclass('public.user_location_pings') IS NULL THEN
                RETURN;
            END IF;
            SELECT count(*) INTO before FROM public.user_location_pings;
            INSERT INTO fieldops.location_pings (
                tenant_id, organization_id, user_id, recorded_at, uuid, client_timestamp, received_at,
                occurred_at, time_basis, kind, coordinates, accuracy_m, altitude_m, heading_deg, speed_mps,
                provider, manual_reason, place_id, extras, app_version, app_metadata)
            SELECT o.tenant_id, o.organization_id, o.user_id, o.recorded_at, uuidv7(), o.recorded_at, o.received_at,
                   LEAST(o.recorded_at, o.received_at), 'device_wall_clock', 'continuous', o.coordinates,
                   CASE WHEN o.accuracy_m >= 0 THEN o.accuracy_m END,
                   o.altitude_m,
                   CASE WHEN o.heading_deg >= 0 AND o.heading_deg < 360 THEN o.heading_deg END,
                   CASE WHEN o.speed_mps >= 0 THEN o.speed_mps END,
                   CASE WHEN o.location_source IN ('gps','fused','network','passive','manual')
                        THEN o.location_source ELSE 'gps' END,
                   CASE WHEN o.location_source = 'manual' THEN 'legacy fix (before fieldops)' END,
                   o.place_id,
                   CASE WHEN o.device_id IS NOT NULL THEN jsonb_build_object('legacy_device_id', o.device_id) END,
                   o.app_version, o.app_metadata
              FROM public.user_location_pings o;
            SELECT count(*) INTO after FROM fieldops.location_pings;
            IF after <> before THEN
                RAISE EXCEPTION 'user_location_pings copy mismatch: % source rows, % copied', before, after;
            END IF;
            DROP TABLE public.user_location_pings;
        END $$;
    """)

    # ── registry: shift / visit (commentable) and visit_task ────────────────────────────────
    bind = op.get_bind()
    register_commentable_entity_type(
        bind, code="shift", name="Shift", target_schema="fieldops", target_table="shifts",
        description="Notes on a field worker's shift (manager remarks, explanations of anomalies).")
    register_commentable_entity_type(
        bind, code="visit", name="Visit", target_schema="fieldops", target_table="visits",
        description="The running note stream of a customer visit.")
    op.execute("""
        INSERT INTO core.entity_types (code, name, target_schema, target_table, description, created_by_name)
        VALUES ('visit_task', 'Visit task', 'fieldops', 'visit_tasks',
                'One action performed in a visit (order, payment, sample …)', 'system:migration')
        ON CONFLICT (code) DO NOTHING
    """)

    # ── permissions: catalogue rows, then the existing system roles' new grants ─────────────
    from app.modules.rbac.seed import seed_permissions

    seed_permissions(bind)
    for role_code, codes in _ROLE_GRANTS.items():
        bind.execute(sa.text("""
            INSERT INTO rbac.role_permissions (tenant_id, organization_id, role_id, permission_id,
                                               created_by_name, app_metadata, created_at, updated_at)
            SELECT r.tenant_id, r.organization_id, r.id, p.id, 'system:migration:fieldops', '{}'::jsonb, now(), now()
              FROM roles r
              JOIN rbac.permissions p ON p.permission_code = ANY(:codes)
             WHERE r.code = :role AND r.is_system AND r.grant_mode = 'explicit' AND r.deleted_at IS NULL
            ON CONFLICT (role_id, permission_id) DO NOTHING
        """), {"role": role_code, "codes": list(codes)})

    # ── user_live_locations: recorded_at now holds the fix's CORRECTED business time ────────
    op.alter_column("user_live_locations", "recorded_at", existing_type=sa.DateTime(timezone=True),
                    comment="Business time of the fix (fieldops clock.py: corrected device time)",
                    existing_comment="Device clock")

    # ── DPDP retention rule for the stream (purge stays OFF until the window is decided) ────
    op.execute("""
        INSERT INTO data_retention_schedules
            (data_category, retention_period_days, retention_trigger_event, action, grace_period_days,
             legal_hold_exception, legal_basis, auto_purge_enabled, created_by_name)
        VALUES ('location_history', 180, 'fix_recorded_date', 'delete', 0, false,
                'DPDP Act 2023 — purpose limitation: field-work tracking during shifts', false,
                'system:migration')
        ON CONFLICT (data_category) DO NOTHING
    """)


def downgrade() -> None:
    # ── restore public.user_location_pings (shape of fdbf62102e86 + 3b7f0ae91c46) ────────────
    op.execute("""
        CREATE TABLE public.user_location_pings (
            id BIGSERIAL NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            coordinates geography(POINT,4326),
            place_id BIGINT,
            accuracy_m DOUBLE PRECISION,
            altitude_m DOUBLE PRECISION,
            heading_deg DOUBLE PRECISION,
            speed_mps DOUBLE PRECISION,
            location_source VARCHAR(20),
            device_id VARCHAR(255),
            recorded_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id BIGINT NOT NULL REFERENCES org_management.tenants (id) ON DELETE CASCADE,
            organization_id BIGINT NOT NULL,
            app_version VARCHAR(32),
            app_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_user_location_pings PRIMARY KEY (recorded_at, id),
            CONSTRAINT fk_user_location_pings_tenant_org FOREIGN KEY (tenant_id, organization_id)
                REFERENCES org_management.organizations (tenant_id, id) ON DELETE CASCADE
        ) PARTITION BY RANGE (recorded_at)
    """)
    op.execute("CREATE TABLE user_location_pings_default PARTITION OF user_location_pings DEFAULT")
    op.execute("CREATE INDEX idx_user_location_pings_coordinates ON user_location_pings USING gist (coordinates)")
    op.execute("CREATE INDEX ix_user_location_pings_tenant_id ON user_location_pings (tenant_id)")
    op.execute("CREATE INDEX ix_user_location_pings_tenant_org ON user_location_pings (tenant_id, organization_id)")
    op.execute("CREATE INDEX ix_user_location_pings_time ON user_location_pings (tenant_id, recorded_at DESC)")
    op.execute("CREATE INDEX ix_user_location_pings_user_id ON user_location_pings (user_id)")
    op.execute("CREATE INDEX ix_user_location_pings_user_time ON user_location_pings "
               "(tenant_id, user_id, recorded_at DESC)")
    op.execute("""
        INSERT INTO public.user_location_pings (user_id, coordinates, place_id, accuracy_m, altitude_m, heading_deg,
            speed_mps, location_source, device_id, recorded_at, received_at, tenant_id, organization_id,
            app_version, app_metadata)
        SELECT user_id, coordinates, place_id, accuracy_m, altitude_m, heading_deg, speed_mps,
               CASE WHEN provider IN ('gps','network','manual') THEN provider ELSE 'gps' END,
               extras ->> 'legacy_device_id', COALESCE(client_timestamp, occurred_at), received_at,
               tenant_id, organization_id, app_version, app_metadata
          FROM fieldops.location_pings
         WHERE coordinates IS NOT NULL
    """)

    op.execute("DELETE FROM data_retention_schedules WHERE data_category = 'location_history' "
               "AND created_by_name = 'system:migration'")
    op.execute("DELETE FROM rbac.role_permissions WHERE created_by_name = 'system:migration:fieldops'")
    op.execute("DELETE FROM comments.commentable_entity_types WHERE entity_type_code IN ('shift','visit') "
               "AND created_by_name = 'system:migration'")
    op.execute("DELETE FROM core.entity_types WHERE code IN ('shift','visit','visit_task') "
               "AND created_by_name = 'system:migration'")

    op.alter_column("user_live_locations", "recorded_at", existing_type=sa.DateTime(timezone=True),
                    comment="Device clock",
                    existing_comment="Business time of the fix (fieldops clock.py: corrected device time)")
    op.execute("DROP VIEW IF EXISTS fieldops.v_ping_flags")
    op.drop_constraint("chk_geofence_visit_enforcement", "geofences", schema="geo", type_="check")
    op.drop_column("geofences", "visit_enforcement", schema="geo")

    for table in ("visit_tasks", "visit_participants", "visits", "shift_pauses", "shift_metrics", "shifts",
                  "device_sessions", "location_pings", "devices", "work_policies", "state_transitions",
                  "ping_batches", "location_checks", "device_events", "anomalies"):
        op.execute(f"DROP TABLE IF EXISTS fieldops.{table} CASCADE")
    op.drop_table("idempotency_keys", schema="core")
    op.execute("DROP SCHEMA IF EXISTS fieldops")
