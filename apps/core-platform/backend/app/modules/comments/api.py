"""HTTP endpoints for comments (mounted at /api/comments)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.comments import schema, service
from app.modules.comments.crud import list_for_owner
from app.modules.rbac.deps import Perm, org_of
from app.modules.users.deps import CurrentUser

router = APIRouter()

_target = org_of("app.modules.comments.model:Comment", param="comment_id")


@router.get("/{owner_type}/{owner_id}", response_model=ResponseModel[list[schema.CommentOut]])
async def list_comments(
    _: CurrentUser, db: DBSession, owner_type: str, owner_id: int, limit: int = Query(100, le=500),
):
    rows = await list_for_owner(db, owner_type=owner_type, owner_id=owner_id, limit=limit)
    return ResponseModel(data=[schema.CommentOut.model_validate(c) for c in rows])


@router.post("", response_model=ResponseModel[schema.CommentOut], status_code=201)
async def create_comment(user: Perm("comments.comment:create"), db: DBSession, body_in: schema.CommentCreate):
    comment = await service.create_comment(db, body_in, actor_id=user.id)
    return ResponseModel(data=schema.CommentOut.model_validate(comment), msg="Comment created")


@router.patch("/{comment_id}", response_model=ResponseModel[schema.CommentOut])
async def update_comment(
    user: Perm("comments.comment:update"), db: DBSession, comment_id: int, body_in: schema.CommentUpdate,
):
    comment = await service.update_comment(db, comment_id, body_in, actor_id=user.id)
    return ResponseModel(data=schema.CommentOut.model_validate(comment), msg="Comment updated")


@router.delete("/{comment_id}", response_model=ResponseModel[None])
async def delete_comment(user: Perm("comments.comment:delete"), db: DBSession, comment_id: int):
    await service.delete_comment(db, comment_id, actor_id=user.id)
    return ResponseModel(data=None, msg="Comment deleted")


@router.patch("/{comment_id}/moderate", response_model=ResponseModel[schema.CommentOut])
async def moderate_update_comment(
    user: Perm("comments.comment:manage", target=_target), db: DBSession, comment_id: int,
    body_in: schema.CommentUpdate,
):
    """Edit ANY comment (not just your own) — admin/moderator only."""
    comment = await service.update_comment(db, comment_id, body_in, actor_id=user.id, force=True)
    return ResponseModel(data=schema.CommentOut.model_validate(comment), msg="Comment updated")


@router.delete("/{comment_id}/moderate", response_model=ResponseModel[None])
async def moderate_delete_comment(user: Perm("comments.comment:manage", target=_target), db: DBSession, comment_id: int):
    """Remove ANY comment (not just your own) — admin/moderator only."""
    await service.delete_comment(db, comment_id, actor_id=user.id, force=True)
    return ResponseModel(data=None, msg="Comment deleted")
