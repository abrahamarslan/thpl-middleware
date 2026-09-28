"""Drop the dead profile-image filename columns from ``users``.

Profile pictures are ``media.items`` rows (``model_type='user'``,
``collection='avatar'``) served as public URLs via the media module. The legacy
``users.image`` / ``users.avatar`` / ``users.thumbnail`` / ``users.preview_image``
filename columns had no reader left and only invited a second, drifting source of
truth for the same picture.

Revision ID: a3f1c9d2e7b4
Revises: cbdb4590446e
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1c9d2e7b4"
down_revision: str | None = "cbdb4590446e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("image", "avatar", "thumbnail", "preview_image")


def upgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("users", column)


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("image", sa.String(length=255), nullable=True,
                  comment="Filename of the main profile picture"),
    )
    op.add_column(
        "users",
        sa.Column("avatar", sa.String(length=255), nullable=True,
                  comment="Filename of the avatar image"),
    )
    op.add_column(
        "users",
        sa.Column("thumbnail", sa.String(length=255), nullable=True,
                  comment="Filename of the profile picture thumbnail"),
    )
    op.add_column(
        "users",
        sa.Column("preview_image", sa.String(length=255), nullable=True,
                  comment="Filename of a preview-sized profile image"),
    )
