"""Seed the permission catalogue — insert-missing, never overwrite.

Same pattern as ``custom_fields/seed.py``: a lightweight Core table (not the ORM
model, so an old migration keeps working after the model grows), a Core insert
with ``ON CONFLICT DO NOTHING``. Codes that LEFT ``catalogue.py`` get
``deprecated_at`` set (never deleted: old grants stay readable); a code that comes
back is un-deprecated.

Called from the migration that creates the table, from ``scripts/seed.py`` and — as
a cheap boot check — from application startup, so forgetting to seed can never become
a permanent 403. It touches the catalogue ONLY, never a role's grants.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.catalogue import PERMISSIONS
from app.modules.rbac.enums import RBAC_SCHEMA

_TABLE = sa.table(
    "permissions",
    sa.column("id", sa.BigInteger),
    sa.column("module_name", sa.String),
    sa.column("resource_name", sa.String),
    sa.column("action_name", sa.String),
    sa.column("permission_code", sa.String),
    sa.column("description", sa.Text),
    sa.column("is_system", sa.Boolean),
    sa.column("owner_only", sa.Boolean),
    sa.column("deprecated_at", sa.DateTime(timezone=True)),
    schema=RBAC_SCHEMA,
)


def catalogue_rows() -> list[dict]:
    return [
        {
            "module_name": p.module, "resource_name": p.resource, "action_name": p.action,
            "description": p.description or None, "is_system": True, "owner_only": p.owner_only,
        }
        for p in PERMISSIONS.values()
    ]


def seed_permissions(conn: Connection) -> int:
    """Insert the catalogue rows that are missing; reconcile ``deprecated_at``. Returns rows inserted."""
    rows = catalogue_rows()
    inserted = len(conn.execute(
        pg_insert(_TABLE).values(rows).on_conflict_do_nothing(constraint="uq_permissions_code")
        .returning(_TABLE.c.id)
    ).all())
    known = list(PERMISSIONS)
    conn.execute(
        sa.update(_TABLE).where(_TABLE.c.permission_code.not_in(known), _TABLE.c.deprecated_at.is_(None))
        .values(deprecated_at=sa.func.now())
    )
    conn.execute(
        sa.update(_TABLE).where(_TABLE.c.permission_code.in_(known), _TABLE.c.deprecated_at.is_not(None))
        .values(deprecated_at=None)
    )
    return inserted


async def ensure_permissions(db: AsyncSession) -> int:
    """Async boot check: make sure every catalogue code has a row (cheap when it already does)."""
    count = await db.scalar(
        sa.select(sa.func.count()).select_from(_TABLE).where(_TABLE.c.deprecated_at.is_(None))
    )
    if count == len(PERMISSIONS):
        return 0
    return await db.run_sync(lambda session: seed_permissions(session.connection()))


__all__ = ["catalogue_rows", "ensure_permissions", "seed_permissions"]
