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
organization is the user's own, or the ``X-Organization-Id`` / ``X-Organization-Code``
header (an organization of the SAME tenant). Both headers are optional: a
malformed ``X-Organization-Id`` is treated as a code rather than refused, so an
optional header never blocks a request.
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
    x_organization_code: Annotated[str | None, Header(alias="X-Organization-Code")] = None,
) -> User:
    user = await _authenticate(db, credentials)
    await _bind_tenancy(db, user, org_uuid=x_organization_id, org_code=x_organization_code)
    return user


OrganizationCode = Annotated[
    str | None,
    Header(
        alias="X-Organization-Code",
        description="Organization code (e.g. THPL) this request acts on. "
                    "Omitted: the deployment default (DEFAULT_ORGANIZATION_CODE).",
    ),
]


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


def _is_uuid(value: str) -> bool:
    """True when ``value`` is a syntactically valid UUID."""
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


async def _bind_tenancy(
    db, user: User, *, org_uuid: str | None = None, org_code: str | None = None,
) -> None:
    """Bind the request to the organization it acts on.

    An authenticated caller may name a *different* organization — a branch they
    also work in — but only one of **their own tenant**: both lookups are
    confined by ``for_tenant``, so neither header can reach across tenants.
    Naming nothing binds the user's own organization.

    ``X-Organization-Id`` is documented as a uuid, but a client that only holds
    the human-readable code routinely sends it here — and the code is the
    resolution-order-first form anyway. A non-uuid value is therefore treated as
    a code instead of refused: an optional header must never block a request. An
    explicit ``X-Organization-Code`` still wins when both are present.
    """
    from app.database import scope
    from app.database.tenancy import bind_user
    from app.modules.tenants import service as tenants

    if user.tenant_id is not None and not tenants.can_sign_in(await tenants.tenant_status(db, user.tenant_id)):
        raise ForbiddenError("Your organization's account is suspended or closed; contact your administrator")

    organization_id = None
    if org_uuid and not _is_uuid(org_uuid):
        org_code = org_code or org_uuid
        org_uuid = None
    if org_code or org_uuid:
        chosen = await scope.resolve(
            db, org_code=org_code, org_uuid=org_uuid, for_tenant=user.tenant_id,
        )
        organization_id = chosen.organization_id if chosen else None
    bind_user(user, organization_id=organization_id)


CurrentUser = Annotated[User, Depends(get_current_user)]
