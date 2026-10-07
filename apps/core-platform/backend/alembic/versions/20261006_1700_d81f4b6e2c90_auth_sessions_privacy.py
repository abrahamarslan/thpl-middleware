"""Sign-in sessions (schema ``auth``) and the privacy-settings vocabulary.

* ``auth.user_sessions`` — one row per first-party sign-in; tokens carry its uuid as ``sid`` and every
  request checks it, so logout and the field app's single-session rule revoke tokens immediately
  (docs/auth/sessions.md). Existing tokens have no ``sid`` and keep working until they expire
  (``AUTH_REQUIRE_SESSION`` stays off until then).
* ``users.application_settings.privacy`` normalized to the current vocabulary
  (docs/users/privacy-settings.md): ``profile_visibility`` ``public``/``organization`` → ``everyone``,
  ``contacts`` → ``team`` (``private`` unchanged); ``show_email``/``show_phone`` → ``contact_visibility``
  (both true → ``everyone``, otherwise ``hidden`` — the old default exposed nothing, so nothing
  becomes visible that was hidden). Downgrade maps back (``everyone`` → ``organization``, ``team`` →
  ``contacts``, ``managers`` → ``contacts``; contact visibility → the two booleans) and KEEPS the exact
  values (``contact_visibility`` stays, ``profile_visibility_v2`` stashes the profile value; older code
  ignores unknown keys), so downgrade → upgrade never widens what someone chose to hide.

Revision ID: d81f4b6e2c90
Revises: c3d9a7e2f415
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d81f4b6e2c90"
down_revision: str | None = "c3d9a7e2f415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRIVACY_UP = """
UPDATE users SET application_settings = jsonb_set(
    application_settings, '{privacy}',
    (application_settings->'privacy') - 'show_email' - 'show_phone' - 'profile_visibility_v2'
    || jsonb_build_object(
        'profile_visibility',
        COALESCE(application_settings->'privacy'->>'profile_visibility_v2',
        CASE application_settings->'privacy'->>'profile_visibility'
             WHEN 'public' THEN 'everyone' WHEN 'organization' THEN 'everyone' WHEN 'contacts' THEN 'team'
             ELSE COALESCE(application_settings->'privacy'->>'profile_visibility', 'everyone') END),
        'contact_visibility',
        COALESCE(application_settings->'privacy'->>'contact_visibility',
                 CASE WHEN COALESCE((application_settings->'privacy'->>'show_email')::bool, false)
                       AND COALESCE((application_settings->'privacy'->>'show_phone')::bool, false)
                      THEN 'everyone' ELSE 'hidden' END)))
 WHERE jsonb_typeof(application_settings->'privacy') = 'object'
"""

_PRIVACY_DOWN = """
UPDATE users SET application_settings = jsonb_set(
    application_settings, '{privacy}',
    (application_settings->'privacy')
    || jsonb_build_object(
        'profile_visibility_v2', application_settings->'privacy'->>'profile_visibility',
        'profile_visibility',
        CASE application_settings->'privacy'->>'profile_visibility'
             WHEN 'everyone' THEN 'organization' WHEN 'team' THEN 'contacts' WHEN 'managers' THEN 'contacts'
             ELSE COALESCE(application_settings->'privacy'->>'profile_visibility', 'organization') END,
        'show_email', (application_settings->'privacy'->>'contact_visibility') IN ('everyone', 'team'),
        'show_phone', (application_settings->'privacy'->>'contact_visibility') IN ('everyone', 'team')))
 WHERE jsonb_typeof(application_settings->'privacy') = 'object'
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")
    op.create_table('user_sessions',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('client_type', sa.String(length=12), nullable=False, comment='field_app | web | service'),
    sa.Column('installation_id', sa.String(length=64), nullable=True, comment='fieldops.devices.installation_id, if sent'),
    sa.Column('device_label', sa.String(length=160), nullable=True, comment="e.g. 'android · Samsung Galaxy M14'"),
    sa.Column('ip_address', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.Text(), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, comment='Absolute cap (SESSION_MAX_DAYS)'),
    sa.Column('refresh_jti_hash', sa.String(length=64), nullable=True, comment='sha256 of the CURRENT refresh jti'),
    sa.Column('previous_refresh_jti_hash', sa.String(length=64), nullable=True, comment='sha256 of the jti it replaced — presenting it again = reuse = theft signal'),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_reason', sa.String(length=24), nullable=True),
    sa.Column('revoked_by_session_id', sa.BigInteger(), nullable=True, comment='The sign-in that displaced it'),
    sa.Column('drain_until', sa.DateTime(timezone=True), nullable=True, comment='Displaced field session: may upload queued fixes until then'),
    sa.Column('uuid', sa.UUID(), server_default=sa.text('uuidv7()'), nullable=False, comment='Time-ordered public reference id (PG18 uuidv7())'),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.BigInteger(), nullable=False, comment='Tenant isolation key'),
    sa.Column('organization_id', sa.BigInteger(), nullable=False, comment='Organization within the tenant (required)'),
    sa.Column('app_version', sa.String(length=32), nullable=True, comment='App version that last wrote the row'),
    sa.Column('app_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("client_type IN ('field_app', 'web', 'service')", name='chk_user_sessions_client_type'),
    sa.CheckConstraint("revoked_reason IS NULL OR revoked_reason IN ('logout', 'logout_all', 'signed_in_elsewhere', 'refresh_reuse', 'admin', 'password_changed', 'user_deactivated', 'expired')", name='chk_user_sessions_revoked_reason'),
    sa.CheckConstraint('(revoked_at IS NULL) = (revoked_reason IS NULL)', name='chk_user_sessions_revoked_pair'),
    sa.ForeignKeyConstraint(['tenant_id', 'organization_id'], ['org_management.organizations.tenant_id', 'org_management.organizations.id'], name='fk_user_sessions_tenant_org', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id', 'user_id'], ['users.tenant_id', 'users.id'], name='fk_user_sessions_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['org_management.tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='auth',
    comment='First-party sign-in sessions (tokens carry the uuid as sid).'
    )
    op.create_index(op.f('ix_auth_user_sessions_tenant_id'), 'user_sessions', ['tenant_id'], unique=False, schema='auth')
    op.create_index(op.f('ix_auth_user_sessions_uuid'), 'user_sessions', ['uuid'], unique=True, schema='auth')
    op.create_index('ix_user_sessions_live', 'user_sessions', ['tenant_id', 'user_id', 'client_type'], unique=False, schema='auth', postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_index('ix_user_sessions_tenant_org', 'user_sessions', ['tenant_id', 'organization_id'], unique=False, schema='auth')
    op.create_index('ix_user_sessions_user', 'user_sessions', ['tenant_id', 'user_id', sa.literal_column('created_at DESC')], unique=False, schema='auth')
    op.execute(_PRIVACY_UP)


def downgrade() -> None:
    op.execute(_PRIVACY_DOWN)
    op.drop_table('user_sessions', schema='auth')
    op.execute("DROP SCHEMA IF EXISTS auth")
