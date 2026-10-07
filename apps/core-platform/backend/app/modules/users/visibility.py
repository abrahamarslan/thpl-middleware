"""Privacy enforcement — what a VIEWER may see of other people (docs/users/privacy-settings.md).

Audiences of (viewer, subject), computed for a whole page in at most two queries:

``self``      the viewer IS the subject
``admin``     the viewer holds ``users.user:read`` (decided by the caller from the grants)
``manager``   the viewer is in the subject's reporting line (any depth, ``employment_records``) or leads a
              team the subject is an approved member of
``team``      viewer and subject share an approved, active team membership
``tenant``    same tenant (every signed-in user — the only audience "everyone" needs)

Rules (the subject's own settings):

=======================  ==========================================================
profile ``everyone``     tenant
profile ``team``         team ∪ manager
profile ``managers``     manager
profile ``private``      nobody else
contact ``everyone``     tenant
contact ``team``         team ∪ manager
contact ``hidden``       nobody else
=======================  ==========================================================

``self`` and ``admin`` always see everything. A hidden profile still shows ``id`` + ``name`` (assigning
a shift or mentioning someone needs them) with ``restricted: true``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PROFILE = {"everyone": {"tenant"}, "team": {"team", "manager"}, "managers": {"manager"}, "private": set()}
_CONTACT = {"everyone": {"tenant"}, "team": {"team", "manager"}, "hidden": set()}


async def audiences(db: AsyncSession, viewer: Any, subject_ids: list[int], *, admin: bool) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {sid: {"tenant"} for sid in subject_ids}
    for sid in subject_ids:
        if sid == viewer.id:
            out[sid].add("self")
        if admin:
            out[sid].add("admin")
    others = [sid for sid in subject_ids if sid != viewer.id]
    if not others or admin:
        return out
    team_rows = (await db.execute(text("""
        SELECT DISTINCT them.user_id, (t.team_lead_user_id = :me) AS i_lead
          FROM teams.user_teams them
          JOIN teams.teams t ON t.id = them.team_id AND t.deleted_at IS NULL
          LEFT JOIN teams.user_teams me ON me.team_id = them.team_id AND me.user_id = :me
               AND me.deleted_at IS NULL AND me.status = 'active' AND me.approval_status = 'approved'
               AND (me.valid_until IS NULL OR me.valid_until > now())
         WHERE them.user_id = ANY(CAST(:ids AS bigint[])) AND them.deleted_at IS NULL AND them.status = 'active'
           AND them.approval_status = 'approved' AND (them.valid_until IS NULL OR them.valid_until > now())
           AND (me.id IS NOT NULL OR t.team_lead_user_id = :me)
    """), {"me": viewer.id, "ids": others})).all()
    for row in team_rows:
        out[row.user_id].add("team")
        if row.i_lead:
            out[row.user_id].add("manager")
    chain = (await db.execute(text("""
        WITH RECURSIVE line(user_id, manager_id, depth) AS (
            SELECT e.user_id, e.reporting_manager_user_id, 1 FROM employment_records e
             WHERE e.user_id = ANY(CAST(:ids AS bigint[])) AND e.is_current AND e.deleted_at IS NULL
            UNION
            SELECT line.user_id, e.reporting_manager_user_id, line.depth + 1
              FROM line JOIN employment_records e ON e.user_id = line.manager_id AND e.is_current
                   AND e.deleted_at IS NULL
             WHERE line.depth < 10
        )
        SELECT DISTINCT user_id FROM line WHERE manager_id = :me
    """), {"me": viewer.id, "ids": others})).scalars().all()
    for sid in chain:
        out[sid].add("manager")
    return out


def _sees(levels: dict[str, set[str]], setting: str, audience: set[str]) -> bool:
    if audience & {"self", "admin"}:
        return True
    return bool(levels.get(setting, set()) & audience)


def can_view_profile(setting: str, audience: set[str]) -> bool:
    return _sees(_PROFILE, setting, audience)


def can_view_contact(setting: str, audience: set[str]) -> bool:
    return _sees(_CONTACT, setting, audience)


def privacy_of(user: Any) -> tuple[str, str]:
    from app.modules.users.schema import PrivacySettings

    raw = (user.application_settings or {}).get("privacy") if isinstance(user.application_settings, dict) else None
    try:
        privacy = PrivacySettings.model_validate(raw or {})
    except ValueError:
        privacy = PrivacySettings()
    return privacy.profile_visibility, privacy.contact_visibility


__all__ = ["audiences", "can_view_contact", "can_view_profile", "privacy_of"]
