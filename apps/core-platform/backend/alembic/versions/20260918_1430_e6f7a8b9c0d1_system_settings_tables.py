"""system settings tables (hierarchical settings module) — previously unmigrated

`app/modules/system/model.py` (SystemModule → SettingGroup → SettingDefinition →
SettingValue, plus SettingAuditLog) shipped without a migration, so every
database built from Alembic lacked these tables and
``system_settings_service`` failed at its first query. The Zoho control plane
stores its audited switches and runtime overrides here, which surfaced the gap
(docs/zoho-sync-implementation/ERRORS-AND-THEIR-RESOLUTIONS.md E12).

Defensive by design: an environment where someone created the tables by hand
(e.g. ``create_all`` during development) must still upgrade, so every table,
index and enum type is created only if absent. Enum labels are the Python
member NAMES, which is how SQLAlchemy persists ``enum.Enum`` columns.

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SETTING_TYPE = postgresql.ENUM(
    "STRING", "INTEGER", "FLOAT", "BOOLEAN", "JSON", name="setting_type_enum", create_type=False
)
_SETTING_CONTEXT = postgresql.ENUM("GLOBAL", "TENANT", "USER", name="setting_context_enum", create_type=False)


def _exists(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("STRING", "INTEGER", "FLOAT", "BOOLEAN", "JSON", name="setting_type_enum").create(
        bind, checkfirst=True
    )
    postgresql.ENUM("GLOBAL", "TENANT", "USER", name="setting_context_enum").create(bind, checkfirst=True)

    if not _exists("system_modules"):
        op.create_table(
            "system_modules",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("version", sa.String(length=50), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_system_modules_name"), "system_modules", ["name"], unique=True)

    if not _exists("setting_groups"):
        op.create_table(
            "setting_groups",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("module_id", sa.BigInteger(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["module_id"], ["system_modules.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _exists("setting_definitions"):
        op.create_table(
            "setting_definitions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("group_id", sa.BigInteger(), nullable=False),
            sa.Column("key", sa.String(length=150), nullable=False),
            sa.Column("name", sa.String(length=150), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("value_type", _SETTING_TYPE, nullable=False),
            sa.Column("default_value", sa.String(length=500), nullable=True),
            sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_overridable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["setting_groups.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_setting_definitions_key"), "setting_definitions", ["key"], unique=True)

    if not _exists("setting_values"):
        op.create_table(
            "setting_values",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("definition_id", sa.BigInteger(), nullable=False),
            sa.Column("context_type", _SETTING_CONTEXT, nullable=False),
            sa.Column("context_id", sa.String(length=100), nullable=True),
            sa.Column("value", sa.String(length=500), nullable=False),
            sa.Column("updated_by", sa.String(length=100), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["definition_id"], ["setting_definitions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_setting_values_context_id"), "setting_values", ["context_id"])
        op.create_index(op.f("ix_setting_values_context_type"), "setting_values", ["context_type"])

    if not _exists("setting_audit_logs"):
        op.create_table(
            "setting_audit_logs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("setting_value_id", sa.BigInteger(), nullable=True),
            sa.Column("module_name", sa.String(length=100), nullable=False),
            sa.Column("definition_key", sa.String(length=150), nullable=False),
            sa.Column("context_type", _SETTING_CONTEXT, nullable=False),
            sa.Column("context_id", sa.String(length=100), nullable=True),
            sa.Column("old_value", sa.String(length=500), nullable=True),
            sa.Column("new_value", sa.String(length=500), nullable=False),
            sa.Column("changed_by", sa.String(length=100), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.ForeignKeyConstraint(["setting_value_id"], ["setting_values.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_setting_audit_logs_changed_at"), "setting_audit_logs", ["changed_at"])
        op.create_index(op.f("ix_setting_audit_logs_definition_key"), "setting_audit_logs", ["definition_key"])
        op.create_index(op.f("ix_setting_audit_logs_module_name"), "setting_audit_logs", ["module_name"])


def downgrade() -> None:
    for table in ("setting_audit_logs", "setting_values", "setting_definitions", "setting_groups", "system_modules"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP TYPE IF EXISTS setting_context_enum")
    op.execute("DROP TYPE IF EXISTS setting_type_enum")
