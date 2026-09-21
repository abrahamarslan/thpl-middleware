"""Who may manage tenants and tenant-level structure.

Interim authorisation until full RBAC (roles exist now; permission checks
arrive with the permissions work):

| Dependency | Allowed |
|---|---|
| ``PlatformAdmin`` | email in ``PLATFORM_ADMIN_EMAILS``; when that list is empty, any authenticated user if ``DEBUG`` (dev) |
| ``TenantAdmin`` | a platform admin, or a user whose role code is ``admin`` / ``owner`` **in their own tenant** |
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import select

from app.common.exception.errors import ForbiddenError
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users.deps import CurrentUser
from app.modules.users.model import User

TENANT_ADMIN_ROLES = frozenset({"admin", "owner"})


def is_platform_admin(user: User) -> bool:
    allowed = {e.strip().lower() for e in settings.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()}
    if allowed:
        return (getattr(user, "email", "") or "").lower() in allowed
    return bool(settings.DEBUG)


async def require_platform_admin(user: CurrentUser) -> User:
    if not is_platform_admin(user):
        raise ForbiddenError("Platform administrator access required")
    return user


async def require_tenant_admin(user: CurrentUser, db: DBSession) -> User:
    if is_platform_admin(user):
        return user
    role_id = getattr(user, "role_id", None)
    if role_id:
        from app.modules.roles.model import Role

        code = await db.scalar(select(Role.code).where(Role.id == role_id))
        if code in TENANT_ADMIN_ROLES:
            return user
    raise ForbiddenError("Tenant administrator access required")


PlatformAdmin = Annotated[User, Depends(require_platform_admin)]
TenantAdmin = Annotated[User, Depends(require_tenant_admin)]
