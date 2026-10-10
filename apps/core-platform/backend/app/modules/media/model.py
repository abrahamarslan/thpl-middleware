"""``media.items`` — one row per stored file (original + its conversions).

The row records WHERE its bytes live (``disk``) and WHO may see them
(``visibility``), so changing ``MEDIA_STORAGE_DRIVER`` for new uploads never
strands a URL that was already issued, and a private row can never be served
by the public router whatever a caller asks for.

Identity
--------
``uuid`` is the public media id: it is in every URL and prefixes every storage
key (``{uuid}/{variant}.{ext}``). Replacing an avatar mints a NEW row and uuid
instead of overwriting bytes, which is what makes the public URLs safe to
cache forever. The BigInteger ``id`` stays internal, like every table here.

Owner
-----
``model_type`` / ``model_id`` name the owner (``user`` / users.id) with no FK,
same shape as ``geo.place_links`` — one table serves every owner class.

``status`` is the CONVERSION lifecycle (pending → processing → done |
partial_failure). It overrides ``StatusMixin.status`` (whose default is
``active``); the column stays, so the tenancy conformance rules still hold.

Conversions are written by concurrent Celery subtasks, one JSONB key each
(``conversions || jsonb_build_object(k, v)``), never by reading and rewriting
the whole map — see repository_worker.py.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import BigIntPKWithUUIDMixin, OrgEntityMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.media.storage_common import DISKS

MEDIA_SCHEMA = "media"

VISIBILITIES = ("public", "private")
STATUSES = ("pending", "processing", "done", "partial_failure")


def _in(values: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in values)


class Media(BigIntPKWithUUIDMixin, OrgEntityMixin, SoftDeleteFilteredMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(f"visibility IN ({_in(VISIBILITIES)})", name="chk_media_visibility"),
        CheckConstraint(f"disk IN ({_in(DISKS)})", name="chk_media_disk"),
        CheckConstraint(f"status IN ({_in(STATUSES)})", name="chk_media_status"),
        CheckConstraint("size_bytes >= 0", name="chk_media_size"),
        # THE read path: "this owner's live media in a collection".
        Index("ix_media_items_owner", "tenant_id", "model_type", "model_id", "collection",
              postgresql_where=text("deleted_at IS NULL")),
        # (The GC sweep — soft-deleted rows past the grace window — is served by the
        # deleted_at index SoftDeleteMixin already declares.)
        {"schema": MEDIA_SCHEMA, "comment": "Stored files (originals) and their generated conversions."},
    )

    model_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Owning entity class, e.g. 'user' (no FK)",
    )
    model_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Owning entity id (no FK)")
    collection: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Named group per owner: 'avatar', 'documents', …",
    )
    disk: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Where THIS file lives: local | garage (never inferred from settings)",
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default=text("'private'"),
        comment="public | private — decides the bucket and whether /public/m may serve it",
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False, comment="Storage key of the ORIGINAL")
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
        comment='{variant: {status, file_name, w, h, size}} — one key per variant, written by Celery',
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'"),
        comment="Conversion lifecycle: pending | processing | done | partial_failure",
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0"),
        comment="Order inside a gallery collection (0 for single-image collections)",
    )
