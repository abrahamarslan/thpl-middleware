"""HasDocumentsMixin — documents on any model, one line.

    class Email(IntPKMixin, TenantEntityMixin, HasDocumentsMixin, Base): ...

The documents of an entity are the documents *linked* to it (``document_links``,
any role) — the link, not the document, carries the relationship, so a document
may belong to several entities. The entity is named by
``linkable_type_of(cls)``: the snake_case of the class name (``Email`` →
``email``), the same string the API and ``DocumentLinkableType`` use.

Read path: ``selectinload(Model.documents)`` — one extra query per result set,
zero N+1. Write path: ``documents.crud.attach_documents_to_entity`` /
``documents.service.link_document`` (the relationship is viewonly for async
safety). The owner's primary key must be an integer (``linkable_id`` is a
BigInteger).
"""

import re

from sqlalchemy import and_
from sqlalchemy.orm import declared_attr, foreign, relationship

from app.modules.documents.model import Document, DocumentLink

_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def linkable_type_of(model: type) -> str:
    """``BrandOwner`` -> ``brand_owner`` — the ``linkable_type`` a model's documents carry."""
    return _WORD_BREAK.sub("_", model.__name__).lower()


class HasDocumentsMixin:
    @declared_attr
    def documents(cls):  # noqa: N805
        link = DocumentLink.__table__
        return relationship(
            Document,
            secondary=link,
            primaryjoin=lambda: and_(
                cls.id == foreign(link.c.linkable_id),
                link.c.linkable_type == linkable_type_of(cls),
                link.c.deleted_at.is_(None),          # the soft-delete filter does not reach a secondary table
            ),
            secondaryjoin=lambda: foreign(link.c.document_id) == Document.id,
            viewonly=True,
            order_by=(link.c.sort_order.asc(), Document.created_at.desc()),
        )
