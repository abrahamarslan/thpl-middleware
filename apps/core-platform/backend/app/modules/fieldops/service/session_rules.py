"""The field app's single-session rule, from the policy layers (setting ``session.field``).

``users`` owns sessions but must not import ``fieldops`` (fieldops is a leaf), so this module REGISTERS
a provider with ``users.sessions`` when field operations is loaded. Resolution is identity-only (sign-in
has no shift, so no hub/beat/team context): organization, role and user layers.

``field_max_sessions = 0`` means unlimited. When no layer sets it, the deployment fallback
``FIELD_MAX_SESSIONS`` applies — so "a layer said unlimited" and "nobody said anything" stay different.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conf import settings
from app.modules.users.sessions import SessionRule, register_rule_provider


async def field_session_rule(db: AsyncSession, user: Any) -> SessionRule:
    from app.modules.fieldops.service.policy import resolve_policy

    policy = await resolve_policy(db, user, identity_only=True)
    configured = "session.field.field_max_sessions" in policy.provenance
    on_new = policy.field_on_new_login
    return SessionRule(
        max_sessions=int(policy.field_max_sessions) if configured else int(settings.FIELD_MAX_SESSIONS),
        on_new_login=str(getattr(on_new, "value", on_new)),
        drain_grant_hours=int(policy.field_drain_grant_hours),
    )


register_rule_provider(field_session_rule)

__all__ = ["field_session_rule"]
