"""HasDocumentsMixin — polymorphic attachments on any model, one line.

    class Email(IntPKMixin, TimestampMixin, HasDocumentsMixin, Base): ...

Read path: ``selectinload(Model.documents)`` — one extra query per result
set, zero N+1. Write path: documents.crud.attach_documents_to_entity (the
relationship is viewonly for async safety).
"""

from sqlalchemy import String, cast
from sqlalchemy.orm import declared_attr, foreign, relationship, remote

from app.modules.documents.model import Document


class HasDocumentsMixin:
    @declared_attr
    def documents(cls):  # noqa: N805
        return relationship(
            Document,
            primaryjoin=lambda: (
                cast(cls.id, String) == foreign(remote(Document.documentable_id))
            ) & (Document.documentable_type == cls.__name__),
            viewonly=True,
            order_by=(Document.display_order.asc(), Document.created_at.desc()),
        )
