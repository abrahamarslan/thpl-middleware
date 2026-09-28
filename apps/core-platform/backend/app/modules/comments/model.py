"""Comments — one polymorphic entity, any registered owner.

    CommentableEntityType   GLOBAL  which registered ``core.entity_types`` classes may
                                    carry comments (opt-in, the ``tax.taxable_entity_types``
                                    shape). One row per class.
    Comment                 ENTITY  the polymorphic row: an owner (``owner_type`` +
                                    ``owner_id``) says something, at an instant, in one
                                    organization.

Why this shape. A tax component, a vehicle, a user and a document all want a free-text
note or an activity-trail entry, and Zoho itself attaches comments to almost every
transaction type. One table serves them all: a new commentable class is a registry row
(``registration.register_commentable_entity_type``) + ``HasCommentsMixin`` on its model,
never a migration to this schema — exactly the pattern ``tax.tax_assignments`` and
``core.entity_aliases`` already established for their own polymorphic edges.

Integrity is LIGHTER than ``tax.tax_assignments`` / ``core.entity_aliases`` on purpose —
comments are high-volume, low-stakes, read-mostly rows, and the extra rigor those two pay
for (a deferred trigger proving the specific ``owner_id`` row exists and shares the
comment's tenant/organization) was judged not worth it here:

  * ``owner_type`` is a real FK to ``core.entity_types.code`` — the class must be
    registered before it can be named;
  * ``owner_id`` has no FK (no single target table) and is NOT proved to exist at write
    time — ``comments.service.create_comment`` checks
    ``comments.commentable_entity_types.is_active`` in Python (a friendly 422, not a
    trigger), and that is the only gate;
  * ``comments.find_orphan_comments()`` is the scheduled safety net for what the missing
    trigger would have caught immediately: an owner hard-deleted after the fact.

Scoping. ``OrgEntityMixin`` (tenant + organization NOT NULL): a comment belongs to the
organization its owner does — the user asked for this module to be organization-scoped,
and an owner (a tax component, a vehicle, a user) already always belongs to exactly one.

Zoho. Comments are routinely pulled from Zoho attached to a transaction, so the row mixes
in ``ZohoIdentityMixin`` (``zoho_id``, NULL until/unless ever pushed) + ``ZohoMirrorMixin``
(pull provenance + its own hash-guard, ``zoho_raw_hash`` — this is why the row does NOT
also carry ``HashGuardMixin``: mixins.py's own docstring says the two are the same idea
and a table takes only one). A comment authored inside the app simply never gets a
``zoho_id``.

Write path: strictly through ``comments.service`` (``POST /api/comments``, …) — never by
mutating ``HasCommentsMixin.comments``, which is ``viewonly`` for the same reason
``HasTagsMixin``/``HasTaxesMixin`` are (implicit lazy loads crash async SQLAlchemy, and a
write needs the policy/grant checks the service owns).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import AppMetaMixin, AuditMixin, BigIntPKWithUUIDv7Mixin, OrgEntityMixin, TimestampMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.comments.enums import COMMENTS_SCHEMA
from app.modules.entities.enums import CORE_SCHEMA
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin

_LIVE = text("deleted_at IS NULL")


class CommentableEntityType(BigIntPKWithUUIDv7Mixin, AuditMixin, AppMetaMixin, TimestampMixin, Base):
    """Which entity classes may carry comments (GLOBAL policy — a platform fact, not a
    tenant preference, exactly as ``tax.taxable_entity_types`` is).

    Not soft-deletable, for the same reason ``TaxableEntityType`` is not:
    ``entity_type_code`` is the FK target of ``comments.comments.owner_type`` and a
    partial unique index cannot be an FK target. Retire a class with ``is_active = false``
    — existing comments stay readable, only NEW ones are refused.
    """

    __tablename__ = "commentable_entity_types"
    __table_args__ = (
        UniqueConstraint("entity_type_code", name="uq_commentable_entity_types_code"),
        {"schema": COMMENTS_SCHEMA, "comment": "Which entity classes may carry comments (global)."},
    )

    entity_type_code: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT",
                         name="fk_commentable_entity_types_entity_type"),
        nullable=False, comment="core.entity_types.code — the class must be registered first",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
        comment="false = no NEW comments for this class; existing rows stay readable",
    )
    description: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<CommentableEntityType {self.entity_type_code!r} active={self.is_active}>"


class Comment(BigIntPKWithUUIDv7Mixin, OrgEntityMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin,
             Base):
    """One comment (or synced activity-trail entry) on one owner."""

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint("owner_id > 0", name="ck_comments_owner_id_positive"),
        # The read path: "this owner's comments, newest first" — plain ascending btree;
        # Postgres serves ORDER BY commented_at DESC from it with a cheap backward scan
        # (same convention as tax.tax_assignments' own ix_tax_assignments_owner).
        Index("ix_comments_owner_commented_at", "owner_type", "owner_id", "commented_at", postgresql_where=_LIVE),
        Index("ix_comments_commented_by_user", "commented_by_user_id",
             postgresql_where=text("deleted_at IS NULL AND commented_by_user_id IS NOT NULL")),
        # Zoho mirror doctrine (zoho/sync/mixins.py): each model's own partial unique
        # index on the live zoho_id.
        Index("uq_comments_zoho_id_live", "tenant_id", "zoho_id", unique=True,
             postgresql_where=text("deleted_at IS NULL AND zoho_id IS NOT NULL")),
        {"schema": COMMENTS_SCHEMA, "comment": "Polymorphic comment: an owning entity says something, at an instant."},
    )

    # ---- whose ----------------------------------------------------------------
    owner_type: Mapped[str] = mapped_column(
        Text, ForeignKey(f"{CORE_SCHEMA}.entity_types.code", ondelete="RESTRICT", name="fk_comments_owner_type"),
        nullable=False, comment="core.entity_types.code of the owning entity, opted in via "
                                "comments.commentable_entity_types",
    )
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="The owner's internal id; no FK (polymorphic) — proved at COMMIT",
    )

    # ---- what -------------------------------------------------------------------
    body: Mapped[str | None] = mapped_column(Text, comment="Comment body")
    comment_type: Mapped[str | None] = mapped_column(
        Text, comment="Source classification, e.g. 'system' vs a human author; free text, no CHECK — an unknown "
                      "upstream value must be stored, not halt a sync (Zoho may add values without notice)",
    )
    operation_type: Mapped[str | None] = mapped_column(
        Text, comment="What operation triggered a system-generated comment, if any; free text, no CHECK",
    )
    is_system_generated: Mapped[bool | None] = mapped_column(
        Boolean, Computed("CASE WHEN comment_type IS NULL THEN NULL ELSE lower(comment_type) = 'system' END",
                          persisted=True),
        comment="STORED generated column: lower(comment_type) = 'system'; NULL when comment_type is NULL",
    )

    # ---- who said it --------------------------------------------------------------
    commented_by_external_id: Mapped[str | None] = mapped_column(
        Text, comment="Opaque external (Zoho) actor id, preserved exactly — never parsed as a number",
    )
    commented_by_name: Mapped[str | None] = mapped_column(Text, comment="Write-time display snapshot of the author")
    commented_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="Best-effort resolved internal users.id (no FK — see AuditMixin.created_by for the "
                           "same convention); populated by an identity-matching job, never auto-merged",
    )

    # ---- when -----------------------------------------------------------------
    commented_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Canonical business-effective instant the comment was made",
    )

    @property
    def owner_ref(self) -> tuple[str, int]:
        return self.owner_type, self.owner_id

    def __repr__(self) -> str:
        return f"<Comment {self.owner_type}:{self.owner_id} by={self.commented_by_name!r} at={self.commented_at}>"


__all__ = ["Comment", "CommentableEntityType"]
