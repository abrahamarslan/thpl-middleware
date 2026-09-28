"""Merge heads — comments module + brands Zoho identity

Two independent branches forked from the same parent (`807ccba816ef`, the
teams/RBAC migration) in the same window: the comments module
(`f3a1b6c9d2e7`) and the brands Zoho identity column
(`999509053c9f`). Neither depends on the other; this is the standard
alembic merge, no schema change of its own.

Revision ID: 8f3f9c0b6d65
Revises: f3a1b6c9d2e7, 999509053c9f
Create Date: 2026-09-28
"""

from collections.abc import Sequence

revision: str = "8f3f9c0b6d65"
down_revision: str | tuple[str, ...] | None = ("f3a1b6c9d2e7", "999509053c9f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
