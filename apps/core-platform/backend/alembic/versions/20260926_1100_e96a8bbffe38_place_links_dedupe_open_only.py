"""geo.place_links: the dedupe index covers OPEN links only.

``uq_place_links_dedupe`` said "the same place is not attached twice to an owner
for the same purpose" but counted *closed* links too. Effective dating closes a
superseded ``current`` address instead of deleting it, so an owner who moved
A → B and then back to A (or re-saved the same address) tried to insert a second
row for A next to the closed one — and the unique index turned a legitimate
history into an IntegrityError (a 500 on ``PATCH /api/auth/me/profile``).

The rule that matters is "not attached twice AT THE SAME TIME", so the index now
also requires ``valid_to IS NULL``. Closed rows are history and never collide.

Revision ID: e96a8bbffe38
Revises: a3f1c9d2e7b4
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e96a8bbffe38"
down_revision: str | None = "a3f1c9d2e7b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ["tenant_id", "owner_type", "owner_id", "place_id", "link_type", "purpose"]


def upgrade() -> None:
    op.drop_index("uq_place_links_dedupe", table_name="place_links", schema="geo",
                  postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_place_links_dedupe", "place_links", _COLUMNS, unique=True, schema="geo",
                    postgresql_where=sa.text("deleted_at IS NULL AND valid_to IS NULL"))


def downgrade() -> None:
    # Fails if an owner now holds a closed and an open link to the same place —
    # that is exactly the history this migration allowed; resolve it before rolling back.
    op.drop_index("uq_place_links_dedupe", table_name="place_links", schema="geo",
                  postgresql_where=sa.text("deleted_at IS NULL AND valid_to IS NULL"))
    op.create_index("uq_place_links_dedupe", "place_links", _COLUMNS, unique=True, schema="geo",
                    postgresql_where=sa.text("deleted_at IS NULL"))
