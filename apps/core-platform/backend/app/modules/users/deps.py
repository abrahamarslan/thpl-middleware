"""Users module — auth dependencies.

`CurrentUser` resolves a bearer token to a row in OUR users table, accepting
both token sources:

  - Authentik OIDC tokens (RS256) -> validated via JWKS, user JIT-provisioned
  - first-party tokens (HS256)    -> issued by /api/auth/login

Use it on any endpoint that needs the authenticated user:

    @router.get("/me")
    async def me(user: CurrentUser): ...
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.common.exception.errors import AuthError, ForbiddenError
from app.common.security.authentik import decode_authentik_token, looks_like_authentik_token
from app.common.security.jwt import bearer_scheme, decode_token
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users import crud, service
from app.modules.users.model import User


async def get_current_user(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise AuthError("Missing bearer token")
    token = credentials.credentials

    if settings.AUTHENTIK_ENABLED and looks_like_authentik_token(token):
        claims = await decode_authentik_token(token)
        return await service.provision_from_authentik(db, claims)

    payload = decode_token(token, expected_type="access")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise AuthError("Token subject is not a valid user id") from None
    user = await crud.get_by_id(db, user_id)
    if user is None:
        raise AuthError("User no longer exists")
    if user.is_deactivated or user.deleted_at is not None:
        raise ForbiddenError("Account is deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
