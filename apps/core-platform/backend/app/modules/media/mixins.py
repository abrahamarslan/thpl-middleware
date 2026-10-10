"""HasMediaMixin — media (avatars, photos) on any model, one line.

    class ContactPerson(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, HasMediaMixin, Base): ...

An owner's media are the live ``media.items`` rows with ``model_type = media_owner_type_of(cls)`` and
``model_id = cls.id`` (no FK — the same polymorphic shape as ``geo.place_links``).

Read path: ``selectinload(Model.media)`` — one extra query per result set; ``lazy="raise_on_sql"`` is
the N+1 firewall. Write path: the OWNER's endpoint calls ``media.service.replace_image`` /
``delete_image`` (media doctrine: no generic upload route — the owner endpoint is what authorizes the
write). URLs: ``media.service.media_urls``.
"""

from __future__ import annotations

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.media.model import Media

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def media_owner_type_of(model: type) -> str:
    explicit = getattr(model, "__media_owner_type__", None)
    if explicit:
        return str(explicit)
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasMediaMixin:
    @declared_attr
    def media(cls):  # noqa: N805
        return relationship(
            Media,
            primaryjoin=lambda: and_(
                cls.id == foreign(Media.model_id),
                Media.model_type == media_owner_type_of(cls),
                Media.deleted_at.is_(None),
            ),
            viewonly=True,
            lazy="raise_on_sql",
            order_by=lambda: (Media.collection.asc(), Media.id.desc()),
        )


__all__ = ["HasMediaMixin", "media_owner_type_of"]
