"""Media model + HasMediaMixin (docs/modules-to-implement/media.md).

The polymorphic relationship uses ``lazy="raise_on_sql"`` as a database
firewall: forgetting ``selectinload(Model.media)`` raises loudly instead of
silently degrading into N+1 queries.
"""

import uuid as uuid_mod

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, declared_attr, foreign, mapped_column, relationship, remote

from app.database.db import Base
from app.database.mixins import IntPKMixin, TimestampMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.core.conf import settings


class Media(IntPKMixin, TimestampMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "media"

    uuid: Mapped[uuid_mod.UUID] = mapped_column(
        PgUUID(as_uuid=True), default=uuid_mod.uuid4, unique=True, comment="Public identifier"
    )

    # Polymorphic owner
    model_type: Mapped[str] = mapped_column(String(100), index=True)
    model_id: Mapped[str] = mapped_column(String(64), index=True)

    collection_name: Mapped[str | None] = mapped_column(String(100), default="default", index=True)
    file_name: Mapped[str] = mapped_column(String(255), comment="Stored (disk) file name")
    original_name: Mapped[str | None] = mapped_column(String(255), comment="Client-supplied name")
    mime_type: Mapped[str | None] = mapped_column(String(100))
    disk: Mapped[str | None] = mapped_column(String(20), default="local", comment="Storage driver: local | s3")
    size: Mapped[int | None] = mapped_column(Integer, comment="Bytes")

    # {"thumb": "done", "optimized": "pending"} — filled by the Celery task
    conversions: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    custom_properties: Mapped[dict | None] = mapped_column(JSONB)
    order_column: Mapped[int | None] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_media_owner", "model_type", "model_id", "collection_name"),)

    # ── URL generation (never stored — derived from disk + conversions) ─────
    def _url_for(self, file_name: str) -> str:
        if self.disk == "s3":
            return f"https://{settings.MEDIA_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{file_name}"
        return f"{settings.MEDIA_PUBLIC_BASE_URL.rstrip('/')}/{file_name}"

    @property
    def urls(self) -> dict[str, str]:
        base_name, _, ext = self.file_name.rpartition(".")
        urls = {"original": self._url_for(self.file_name)}
        for conv_name, status in (self.conversions or {}).items():
            if status == "done":
                urls[conv_name] = self._url_for(f"{base_name}-{conv_name}.{ext}")
        return urls


class HasMediaMixin:
    """Polymorphic media gallery for any model.

    Declare conversions on the owning model (Spatie-style):

        __media_conversions__ = {"thumb": (150, 150)}
    """

    __media_conversions__: dict[str, tuple[int, int]] = {}

    @declared_attr
    def media(cls):  # noqa: N805
        from sqlalchemy import String as _String
        from sqlalchemy import cast as _cast

        return relationship(
            Media,
            primaryjoin=lambda: (
                _cast(cls.id, _String) == foreign(remote(Media.model_id))
            ) & (Media.model_type == cls.__name__),
            viewonly=True,
            lazy="raise_on_sql",  # firewall: force explicit selectinload
            order_by=Media.order_column,
        )
