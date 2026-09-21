"""AuditMixin.updated_by_name — the denormalised name of the last updater.

Adds one nullable column to every table that uses ``AuditMixin`` (19 tables)
plus ``users``, which declares its audit columns by hand (20 tables),
symmetrical to ``created_by_name``: history reads without a join to ``users``
and survives the user being deleted. tenancy.py stamps it together with
``updated_by`` from now on.

Existing rows that already carry an ``updated_by`` get the user's *current*
name as a best effort (the name "at the time" is not recoverable); rows updated
by the system have ``updated_by`` NULL and stay NULL.

Additive and fully reversible. ``zoho_retention_policies`` has its own
``updated_by`` (a global settings table, not an entity) and is untouched.

Revision ID: 1aad2ed925a3
Revises: 4f2f2a8c7898
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa

revision = '1aad2ed925a3'
down_revision = '4f2f2a8c7898'
branch_labels = None
depends_on = None

#: (schema, table) of every AuditMixin table, plus users (hand-declared audit columns).
TABLES = [
    (None, "users"),
    (None, "documents"),
    (None, "emails"),
    (None, "favorites"),
    (None, "files"),
    ("geo", "admin_boundaries"),
    ("geo", "geofences"),
    ("geo", "place_links"),
    ("geo", "place_relationships"),
    ("geo", "places"),
    (None, "media"),
    ("org_management", "organizations"),
    ("org_management", "tenants"),
    (None, "roles"),
    (None, "tags"),
    (None, "user_profiles"),
    (None, "zoho_currencies"),
    (None, "zoho_locations"),
    (None, "zoho_taxes"),
    (None, "zoho_users"),
]


def _qualified(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def upgrade() -> None:
    for schema, table in TABLES:
        op.add_column(
            table,
            sa.Column('updated_by_name', sa.String(length=255), nullable=True,
                      comment='Last updater display name at the time'),
            schema=schema,
        )
        op.execute(
            f"UPDATE {_qualified(schema, table)} AS t SET updated_by_name = u.name "
            f"FROM users AS u WHERE t.updated_by = u.id"
        )


def downgrade() -> None:
    for schema, table in reversed(TABLES):
        op.drop_column(table, 'updated_by_name', schema=schema)
