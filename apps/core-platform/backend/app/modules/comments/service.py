"""Comments business logic (service layer).

Ownership, not a second guard paradigm: ``comments.comment:update``/``:delete`` are
member-level (any signed-in user may edit/remove THEIR OWN comment), while
``comments.comment:manage`` (admin+) lets a moderator touch anyone's — the route still
declares exactly one ``Perm()`` each (docs/rbac-module.md §4.2's "one declarative guard"
rule is about the CHECK, not about a plain business rule living in the service it calls,
same as ``rbac.service.ensure_not_last_owner`` or ``moderation.ban_user``'s self-ban guard).
``force=True`` is how the ``/moderate`` route opts out of the ownership check; the real
actor is still recorded, so the activity log always says who actually acted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ForbiddenError, NotFoundError
from app.database import scope
from app.database.tenancy import current_actor
from app.modules.activity.recorder import record_activity
from app.modules.comments import crud, schema
from app.modules.comments.errors import CommentRuleError
from app.modules.comments.model import Comment

# actor_id: int (never a users.model.User) throughout this module — same convention
# tags/taxes services follow for their own actor_id params. app.modules.users.model
# adds HasCommentsMixin (a consumer of comments), so importing User BACK here would
# be the cross-import taxes/assignment_service.py's docstring warns about for its own
# consumer (categories) — .importlinter enforces that one because categories is not
# baseline infra; users.deps (CurrentUser) legitimately is, which is why there is no
# matching contract here, only the convention. commented_by_name is stamped from
# current_actor() — the SAME tenancy-context actor AuditMixin's created_by_name uses.


async def create_comment(db: AsyncSession, body_in: schema.CommentCreate, *, actor_id: int) -> Comment:
    # The only gate left after the DB trigger was removed (see model.py's docstring):
    # a friendly 422 in Python, not a raw Postgres exception at COMMIT. owner_type must
    # still be a REGISTERED core.entity_types code (the table's own FK proves that one);
    # this only adds "and an active comments.commentable_entity_types opt-in row".
    policy = await crud.get_commentable_policy(db, body_in.owner_type)
    if policy is None or not policy.is_active:
        raise CommentRuleError(f"comments are disabled for entity type '{body_in.owner_type}'",
                               data={"owner_type": body_in.owner_type})

    organization_id = await scope.require_organization_id(db)
    actor = current_actor()
    comment = Comment(
        owner_type=body_in.owner_type, owner_id=body_in.owner_id, body=body_in.body,
        comment_type=body_in.comment_type, commented_at=body_in.commented_at or datetime.now(UTC),
        commented_by_user_id=actor_id, commented_by_name=actor.name, organization_id=organization_id,
    )
    db.add(comment)
    await db.flush()
    await record_activity(
        db, action="comment_created", actor_id=actor_id,
        subject_type=body_in.owner_type, subject_id=body_in.owner_id,
        changes={"after": {"comment_id": comment.id, "body": body_in.body}},
    )
    return comment


async def update_comment(
    db: AsyncSession, comment_id: int, body_in: schema.CommentUpdate, *, actor_id: int | None, force: bool = False,
) -> Comment:
    comment = await _get_or_404(db, comment_id)
    _check_owner(comment, actor_id, force=force)
    before = comment.body
    comment.body = body_in.body
    await db.flush()
    await record_activity(
        db, action="comment_updated", actor_id=actor_id,
        subject_type=comment.owner_type, subject_id=comment.owner_id,
        changes={"before": {"body": before}, "after": {"body": comment.body}},
        context={"comment_id": comment.id, "moderated": force},
    )
    return comment


async def delete_comment(db: AsyncSession, comment_id: int, *, actor_id: int | None, force: bool = False) -> None:
    comment = await _get_or_404(db, comment_id)
    _check_owner(comment, actor_id, force=force)
    comment.soft_delete(by=actor_id or current_actor().user_id)
    await db.flush()
    await record_activity(
        db, action="comment_deleted", actor_id=actor_id,
        subject_type=comment.owner_type, subject_id=comment.owner_id,
        context={"comment_id": comment.id, "moderated": force},
    )


async def _get_or_404(db: AsyncSession, comment_id: int) -> Comment:
    comment = await crud.get_comment(db, comment_id)
    if comment is None:
        raise NotFoundError(f"Comment {comment_id} not found")
    return comment


def _check_owner(comment: Comment, actor_id: int | None, *, force: bool) -> None:
    if force:
        return
    if actor_id is None or comment.commented_by_user_id != actor_id:
        raise ForbiddenError(
            "You can only edit or delete your own comment; a moderator needs comments.comment:manage",
        )


__all__ = ["create_comment", "delete_comment", "update_comment"]
