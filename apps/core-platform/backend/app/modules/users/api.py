"""Users module — HTTP endpoints (api layer).

Two routers:
  auth_router  -> /api/auth/*   register, login, refresh, me, passwords, dev-token
  users_router -> /api/users/*  list, get, create, update, soft/hard delete, restore
"""

import secrets

from fastapi import APIRouter, Query

from app.common.exception.errors import ForbiddenError
from app.common.response.schema import PageModel, ResponseModel
from app.common.security.jwt import create_access_token
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users import service
from app.modules.users.deps import CurrentUser
from app.modules.users.schema import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserCreate,
    UserListFilters,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter()
users_router = APIRouter()


# ════════════════════════════════ AUTH ════════════════════════════════════════

@auth_router.post("/register", response_model=ResponseModel[UserOut], status_code=201)
async def register(db: DBSession, body: RegisterRequest):
    user = await service.register(db, body)
    return ResponseModel(data=UserOut.model_validate(user))


@auth_router.post("/login", response_model=ResponseModel[TokenPair])
async def login(db: DBSession, body: LoginRequest):
    _, tokens = await service.login(db, body)
    return ResponseModel(data=tokens)


@auth_router.post("/refresh", response_model=ResponseModel[TokenPair])
async def refresh(db: DBSession, body: RefreshRequest):
    return ResponseModel(data=await service.refresh_tokens(db, body.refresh_token))


@auth_router.get("/me", response_model=ResponseModel[UserOut])
async def me(user: CurrentUser):
    return ResponseModel(data=UserOut.model_validate(user))


@auth_router.post("/change-password", response_model=ResponseModel[dict])
async def change_password(db: DBSession, user: CurrentUser, body: ChangePasswordRequest):
    await service.change_password(
        db, user, current_password=body.current_password, new_password=body.new_password
    )
    return ResponseModel(data={"changed": True})


@auth_router.post("/forgot-password", response_model=ResponseModel[dict])
async def forgot_password(db: DBSession, body: ForgotPasswordRequest):
    result = await service.request_password_reset(db, email=body.email, reset_type=body.reset_type)
    return ResponseModel(data=result)


@auth_router.post("/reset-password", response_model=ResponseModel[dict])
async def reset_password(db: DBSession, body: ResetPasswordRequest):
    await service.reset_password(
        db, email=body.email, token_or_code=body.token_or_code, new_password=body.new_password
    )
    return ResponseModel(data={"reset": True})


@auth_router.post("/dev-token", response_model=ResponseModel[dict], include_in_schema=False)
async def dev_token(db: DBSession):
    """DEBUG-only token mint for local API testing.

    Gets-or-creates a real `dev@local.test` user row so the token works
    against every CurrentUser-protected endpoint (the subject must be a
    numeric user id — a synthetic subject 500s at token use, not mint).
    """
    if not settings.DEBUG:
        raise ForbiddenError("dev-token is only available when DEBUG=true")
    from app.modules.users import crud
    from app.modules.users.service import hash_password

    user = await crud.get_by_email(db, "dev@local.test")
    if user is None:
        user = await crud.create(
            db,
            {
                "email": "dev@local.test",
                "username": "dev",
                "name": "Dev Token User",
                "password": hash_password(secrets.token_urlsafe(24)),  # unusable for login
            },
        )
    return ResponseModel(
        data={"access_token": create_access_token(str(user.id), claims={"scope": "dev"})}
    )


# ════════════════════════════════ USERS ═══════════════════════════════════════

@users_router.get("", response_model=ResponseModel[PageModel[UserOut]])
async def list_users(db: DBSession, _: CurrentUser, filters: UserListFilters = Query()):
    users, total = await service.list_users(db, filters)
    return ResponseModel(
        data=PageModel(
            items=[UserOut.model_validate(u) for u in users],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@users_router.post("", response_model=ResponseModel[UserOut], status_code=201)
async def create_user(db: DBSession, current: CurrentUser, body: UserCreate):
    user = await service.create_user(db, body, created_by=current.id)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.get("/{user_id}", response_model=ResponseModel[UserOut])
async def get_user(
    db: DBSession, _: CurrentUser, user_id: int,
    include_deleted: bool = Query(False, description="Also match soft-deleted users"),
):
    user = await service.get_user(db, user_id, include_deleted=include_deleted)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.put("/{user_id}", response_model=ResponseModel[UserOut])
async def update_user(db: DBSession, current: CurrentUser, user_id: int, body: UserUpdate):
    user = await service.update_user(db, user_id, body, updated_by=current.id)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.delete("/{user_id}", response_model=ResponseModel[dict])
async def delete_user(
    db: DBSession, current: CurrentUser, user_id: int,
    hard: bool = Query(False, description="Permanently delete instead of soft delete"),
):
    await service.delete_user(db, user_id, deleted_by=current.id, hard=hard)
    return ResponseModel(data={"deleted": True, "hard": hard})


@users_router.post("/{user_id}/restore", response_model=ResponseModel[UserOut])
async def restore_user(db: DBSession, _: CurrentUser, user_id: int):
    user = await service.restore_user(db, user_id)
    return ResponseModel(data=UserOut.model_validate(user))
