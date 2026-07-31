"""Tags model — multilingual tags + the polymorphic taggables pivot.

``name``/``slug`` are JSONB maps keyed by locale ({"en": "Urgent"}), giving
multi-lingual support natively. The pivot uses a composite primary key
(tag_id, taggable_id, taggable_type) — uniqueness is structural, no
surrogate id needed. ``taggable_id`` is String so Integer-PK and UUID-PK
entities coexist in one pivot.
"""

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin


class Tag(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[dict] = mapped_column(JSONB, nullable=False, comment='Locale map, e.g. {"en": "Urgent"}')
    slug: Mapped[dict] = mapped_column(JSONB, nullable=False, comment='Locale map, e.g. {"en": "urgent"}')
    type: Mapped[str | None] = mapped_column(String(100), index=True, comment="Namespace, e.g. 'badges'")
    order_column: Mapped[int | None] = mapped_column(Integer, default=0)


class Taggable(TimestampMixin, Base):
    __tablename__ = "taggables"

    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    taggable_id: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    taggable_type: Mapped[str] = mapped_column(String(100), primary_key=True, index=True)
