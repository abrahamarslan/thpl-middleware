"""Comments data access (SQL only; no business rules)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comments.model import Comment, CommentableEntityType


async def get_comment(db: AsyncSession, comment_id: int) -> Comment | None:
    return await db.get(Comment, comment_id)


async def get_commentable_policy(db: AsyncSession, owner_type: str) -> CommentableEntityType | None:
    return await db.scalar(
        select(CommentableEntityType).where(CommentableEntityType.entity_type_code == owner_type)
    )


async def list_for_owner(
    db: AsyncSession, *, owner_type: str, owner_id: int, limit: int = 100,
) -> list[Comment]:
    stmt = (
        select(Comment)
        .where(Comment.owner_type == owner_type, Comment.owner_id == owner_id)
        # No manual organization_id filter: the deferred owner-scope trigger already
        # guarantees every live comment for this owner shares the owner's one
        # organization, and the tenant filter is automatic (app/database/tenancy.py).
        .order_by(Comment.commented_at.desc(), Comment.id.desc())
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


__all__ = ["get_comment", "list_for_owner"]
