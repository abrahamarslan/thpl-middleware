"""Users module — auth dependencies.

`CurrentUser` resolves a bearer token to a row in OUR users table, accepting
both token sources:

  - Authentik OIDC tokens (RS256) -> validated via JWKS, user JIT-provisioned
  - first-party tokens (HS256)    -> issued by /api/auth/login

Use it on any endpoint that needs the authenticated user:

    @router.get("/me")
    async def me(user: CurrentUser): ...

Tenancy (docs/tenancy/README.md §4): after authentication the request is bound
to the user's tenant — every ORM query is filtered to it and every insert is
stamped with it. A user of a suspended/cancelled tenant is refused. The active
organization is the user's own, or the ``X-Organization-Id`` header (uuid of
an organization of the SAME tenant).
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials

from app.common.exception.errors import AuthError, ForbiddenError
from app.common.security.authentik import decode_authentik_token, looks_like_authentik_token
from app.common.security.jwt import bearer_scheme, decode_token
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users import crud, moderation, service
from app.modules.users.model import User


async def get_current_user(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_organization_id: Annotated[str | None, Header(alias="X-Organization-Id")] = None,
) -> User:
    user = await _authenticate(db, credentials)
    await _bind_tenancy(db, user, x_organization_id)
    return user


async def _authenticate(db, credentials: HTTPAuthorizationCredentials | None) -> User:
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
    moderation.ensure_can_use_api(user)
    return user


async def _bind_tenancy(db, user: User, organization_header: str | None) -> None:
    from sqlalchemy import select

    from app.database.tenancy import bind_user
    from app.modules.organizations.model import Organization
    from app.modules.tenants import service as tenants

    if user.tenant_id is not None and not tenants.can_sign_in(await tenants.tenant_status(db, user.tenant_id)):
        raise ForbiddenError("Your organization's account is suspended or closed; contact your administrator")

    organization_id = None
    if organization_header:
        try:
            org_uuid = uuid.UUID(organization_header)
        except ValueError:
            raise ForbiddenError("X-Organization-Id must be an organization uuid") from None
        organization_id = await db.scalar(
            select(Organization.id).where(Organization.uuid == org_uuid, Organization.tenant_id == user.tenant_id)
        )
        if organization_id is None:
            raise ForbiddenError("X-Organization-Id is not an organization of your tenant")
    bind_user(user, organization_id=organization_id)


CurrentUser = Annotated[User, Depends(get_current_user)]
