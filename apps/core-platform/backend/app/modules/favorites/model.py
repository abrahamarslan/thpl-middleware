"""Favorites model — a user pins any entity type (polymorphic).

One row per (user, target). Unfavoriting hard-deletes the row, so a partial
unique index guarantees a user can't favorite the same target twice.
'favoritable_type'/'favoritable_id' mirror the polymorphic pattern used by
files ('fileable_*') so any module's records can be favorited without schema
changes (e.g. 'zoho_item', 'file', 'user').
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TenantMixin, TimestampMixin


class Favorite(IntPKMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "favorites"

    favorite_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), default=uuid.uuid4, unique=True, index=True, comment="Public UUID"
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Polymorphic target.
    favoritable_type: Mapped[str] = mapped_column(String(100), index=True)
    favoritable_id: Mapped[str] = mapped_column(String(64), index=True)

    # Grouping (e.g. "default", "Wishlist"). NOT NULL with a default so the
    # composite uniqueness below is bulletproof — Postgres treats NULLs as
    # distinct, which would allow duplicate favorites.
    collection_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="default", server_default="default", index=True
    )

    # Optional UI metadata.
    label: Mapped[str | None] = mapped_column(String(255), comment="Display-name snapshot")
    note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0, comment="Manual ordering")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "favoritable_type", "favoritable_id", "collection_name",
            name="uq_favorite_user_target",
        ),
        Index("ix_favorite_user_type", "user_id", "favoritable_type"),
    )
