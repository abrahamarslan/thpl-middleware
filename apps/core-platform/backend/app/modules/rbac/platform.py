"""Platform-level administrators — staff of the platform itself, outside every tenant's RBAC.

Kept in its own leaf module (settings only, no ORM, no other feature) so both
``rbac.engine`` and ``tenants.deps`` can use it without an import cycle.

A platform administrator is an email in ``PLATFORM_ADMIN_EMAILS``. When that list
is empty, anyone is one **only if ``DEBUG`` is true** (local development). Platform
administrators pass every permission check inside the tenant they act in, exactly as
they passed ``TenantAdmin`` before RBAC; their actions are audited like anyone's.
"""

from __future__ import annotations

from typing import Any

from app.core.conf import settings


def platform_admin_emails() -> set[str]:
    return {e.strip().lower() for e in settings.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()}


def is_platform_admin(user: Any) -> bool:
    allowed = platform_admin_emails()
    if allowed:
        return (getattr(user, "email", "") or "").lower() in allowed
    return bool(settings.DEBUG)


__all__ = ["is_platform_admin", "platform_admin_emails"]
