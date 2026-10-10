"""Resolution policies — reading the effective one, overriding it per tenant / organization.

Precedence is configurable through the module, not through code changes: the accountant-
approved defaults are registered in code, and a tenant (or one organization) may store an
override in ``core.resolution_policies``. Overrides are validated against the registered
vocabulary BEFORE they are stored, so the engine never meets a policy it cannot run.
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.core.conf import settings
from app.database.tenancy import current_actor, current_tenant_id
from app.modules.activity.recorder import record_activity
from app.modules.resolution.engine import ResolutionError, effective_policies
from app.modules.resolution.model import ResolutionPolicyOverride
from app.modules.resolution.registry import resolution_registry
from app.modules.resolution.types import Policy, Step

logger = structlog.get_logger("app.resolution.service")


async def effective(db: AsyncSession, facet: str, subject: str, organization_id: int | None) -> Policy:
    return (await effective_policies(db, facet, subject, {organization_id}))[organization_id]


async def _override_row(
    db: AsyncSession, facet: str, subject: str, organization_id: int | None,
) -> ResolutionPolicyOverride | None:
    stmt = select(ResolutionPolicyOverride).where(
        ResolutionPolicyOverride.facet == facet, ResolutionPolicyOverride.subject == subject,
        ResolutionPolicyOverride.organization_id.is_(None) if organization_id is None
        else ResolutionPolicyOverride.organization_id == organization_id,
    )
    return await db.scalar(stmt.limit(1))


async def put_override(
    db: AsyncSession, facet: str, subject: str, *, steps: Sequence[Step], use_organization_default: bool,
    organization_id: int | None, notes: str | None = None, actor_id: int | None = None,
) -> Policy:
    """Store (or replace) the override at this scope. ``organization_id`` None = tenant-wide."""
    default = resolution_registry.policy(facet, subject)
    problems = resolution_registry.problems_of(default, steps)
    if problems:
        raise ResolutionError("; ".join(problems), data={"problems": problems})
    payload = [step.as_dict() for step in steps]
    row = await _override_row(db, facet, subject, organization_id)
    before = None if row is None else {"steps": row.steps, "use_organization_default": row.use_organization_default}
    if row is None and organization_id is None:
        # A TENANT-WIDE row is inserted with Core on purpose: the ORM insert hook stamps a NULL
        # organization_id from the request context (or the default organization), which would silently
        # turn "tenant-wide" into "this organization" (app/database/tenancy.py).
        actor = current_actor()
        await db.execute(insert(ResolutionPolicyOverride).values(
            tenant_id=current_tenant_id(), organization_id=None, facet=facet, subject=subject, steps=payload,
            use_organization_default=use_organization_default, notes=notes, created_by=actor.user_id,
            created_by_name=actor.name, app_version=settings.VERSION,
        ))
    elif row is None:
        db.add(ResolutionPolicyOverride(facet=facet, subject=subject, organization_id=organization_id, steps=payload,
                                        use_organization_default=use_organization_default, notes=notes))
    else:
        row.steps, row.use_organization_default, row.notes = payload, use_organization_default, notes
    await db.flush()
    await record_activity(
        db, action="resolution_policy_overridden", actor_id=actor_id, subject_type="resolution_policy",
        subject_id=f"{facet}/{subject}",
        changes={"before": before, "after": {"steps": payload, "use_organization_default": use_organization_default,
                                             "organization_id": organization_id}},
    )
    logger.info("resolution.policy.overridden", facet=facet, subject=subject, organization_id=organization_id,
                steps=payload)
    return await effective(db, facet, subject, organization_id)


async def delete_override(
    db: AsyncSession, facet: str, subject: str, *, organization_id: int | None, actor_id: int | None = None,
) -> Policy:
    """Drop the override at this scope; the next layer up takes over."""
    resolution_registry.policy(facet, subject)
    row = await _override_row(db, facet, subject, organization_id)
    if row is None:
        raise NotFoundError(f"No override of {facet}/{subject} at this scope")
    row.soft_delete(reason="override removed", by=actor_id)
    await db.flush()
    await record_activity(db, action="resolution_policy_reset", actor_id=actor_id, subject_type="resolution_policy",
                          subject_id=f"{facet}/{subject}", changes={"organization_id": organization_id})
    return await effective(db, facet, subject, organization_id)


__all__ = ["delete_override", "effective", "put_override"]
