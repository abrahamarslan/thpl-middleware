"""Who may manage tenants.

Tenant-level authorization is RBAC now (docs/rbac-module.md): every route declares the permission it
needs with ``rbac.deps.Perm(...)``. What remains here:

| Dependency | Allowed |
|---|---|
| ``PlatformAdmin`` | email in ``PLATFORM_ADMIN_EMAILS``; when that list is empty, any authenticated user **only if** ``DEBUG`` (dev). Platform staff sit OUTSIDE every tenant's RBAC — they manage tenants themselves |
| ``TenantAdmin`` | **deprecated alias** for ``Perm("org.organization:manage")`` — kept so old imports keep working; new code declares the specific permission instead |
"""

from typing import Annotated

from fastapi import Depends

from app.common.exception.errors import ForbiddenError
from app.modules.rbac.deps import Perm
from app.modules.rbac.platform import is_platform_admin
from app.modules.users.deps import CurrentUser
from app.modules.users.model import User


async def require_platform_admin(user: CurrentUser) -> User:
    if not is_platform_admin(user):
        raise ForbiddenError("Platform administrator access required")
    return user


PlatformAdmin = Annotated[User, Depends(require_platform_admin)]

#: Deprecated: declare the specific ``Perm("module.resource:action")`` instead.
TenantAdmin = Perm("org.organization:manage")

__all__ = ["PlatformAdmin", "TenantAdmin", "is_platform_admin", "require_platform_admin"]
