"""seed the fleet-partner agreement document type

Adds ``FLEET_PARTNER_AGREEMENT`` (ENTITY_PROOF) to the ``document_types``
catalog so a fleet partner's signed agreement is attached through the Document
module (verified, versioned, audited) rather than a raw storage key on
``fleet_partners``.

Revision ID: 9c1e2f3a4b5c
Revises: a9c7e412d83b
Create Date: 2026-09-21 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1e2f3a4b5c"
down_revision: str | None = "a9c7e412d83b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.modules.documents.seed import seed_document_types

    seed_document_types(op.get_bind())


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM document_types WHERE code = 'FLEET_PARTNER_AGREEMENT'"))
