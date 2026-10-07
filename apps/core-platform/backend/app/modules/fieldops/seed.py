"""Field-operations defaults for the company tenant (``scripts/seed.py`` step ``fieldops.defaults``).

Seeds, at the company tenant's ROOT organization (docs/fieldops/shift-templates.md §6):

* shift template ``WORK_SHIFT`` — "Work Shift", 09:00 → 21:00 in the company timezone (Asia/Kolkata for
  THPL), every day, work type ``other``, starting and ending ANYWHERE, no geofencing;
* policy layer "<TENANT> default" (organization scope) — ``consent.required = true``, LOCKED (no branch,
  role or user layer can switch DPDP consent off);
* policy layer "<TENANT> members" (role ``member``) — ``shift.template = WORK_SHIFT``; the shift window
  (12 h max, no overtime, 60 min auto-close grace, 60 min early start); ``session.field`` = ONE active
  field-app session (a new sign-in revokes the previous device, 24 h telemetry-drain grant); the THPL
  tracking cadence (45 s base, 3 min when still).

Idempotent the documents-seed way: CREATE IF MISSING, never overwrite — a template or layer an admin
already edited is left exactly as it is. Never run against the pytest database (memory:
seeding-vs-test-database); tests build their own templates and layers.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.conf import settings

logger = structlog.get_logger("app.fieldops.seed")

WORK_SHIFT = "WORK_SHIFT"

TEMPLATE = {
    "code": WORK_SHIFT, "name": "Work Shift", "work_type": "other",
    "description": "The default working day when no shift is scheduled: 09:00–21:00, start and end anywhere.",
    "start_local_time": dt.time(9, 0), "end_local_time": dt.time(21, 0), "end_day_offset": 0,
    "days_of_week": [1, 2, 3, 4, 5, 6, 7],
}

MEMBER_SETTINGS: dict[str, Any] = {
    "shift.template": WORK_SHIFT,
    "shift.window": {"max_shift_hours": 12, "overtime_minutes": 0, "auto_close_grace_minutes": 60,
                     "start_early_minutes": 60, "late_start_grace_minutes": 15, "pre_end_reminder_minutes": 30},
    "session.field": {"field_max_sessions": 1, "field_on_new_login": "revoke_previous",
                      "field_drain_grant_hours": 24},
    "tracking.intervals": {"ping_interval_s": 45, "stationary_interval_s": 180, "ping_min_distance_m": 50},
}


async def seed_fieldops_defaults(db: AsyncSession, *, tenant_code: str, timezone: str | None = None) -> dict:
    from app.database.tenancy import tenant_scope
    from app.modules.fieldops.model import PolicyLayer, ShiftTemplate
    from app.modules.fieldops.policy.resolver import bump_epoch
    from app.modules.fieldops.service.policy import clean_settings
    from app.modules.fieldops.policy.settings import Scope

    tenant = (await db.execute(text("SELECT id, timezone FROM org_management.tenants WHERE tenant_code = :c"),
                               {"c": tenant_code})).first()
    if tenant is None:
        raise RuntimeError(f"tenant {tenant_code} not found — run the company seeder first")
    root = await db.scalar(text("SELECT id FROM org_management.organizations WHERE tenant_id = :t "
                                "AND deleted_at IS NULL ORDER BY depth, id LIMIT 1"), {"t": tenant.id})
    member_role = await db.scalar(text("SELECT id FROM roles WHERE tenant_id = :t AND organization_id = :o "
                                       "AND code = 'member' AND deleted_at IS NULL"), {"t": tenant.id, "o": root})
    created: dict[str, bool] = {"template": False, "default_layer": False, "member_layer": False}
    with tenant_scope(tenant.id, root):
        if await db.scalar(select(ShiftTemplate.id).where(ShiftTemplate.code == WORK_SHIFT)) is None:
            db.add(ShiftTemplate(organization_id=root, timezone=timezone or tenant.timezone or settings.COMPANY_TIMEZONE,
                                 created_by_name="system:seed", **TEMPLATE))
            created["template"] = True
        org_layer = await db.scalar(select(PolicyLayer.id).where(
            PolicyLayer.organization_id == root, PolicyLayer.scope_type == "organization",
            PolicyLayer.effective_from.is_(None)))
        if org_layer is None:
            db.add(PolicyLayer(organization_id=root, name=f"{tenant_code} default", scope_type="organization",
                               description="Tenant-wide fallback. DPDP consent is locked on.",
                               settings=clean_settings(Scope.ORGANIZATION, {"consent.required": True}),
                               locked_keys=["consent.required"], created_by_name="system:seed"))
            created["default_layer"] = True
        if member_role is not None:
            member_layer = await db.scalar(select(PolicyLayer.id).where(
                PolicyLayer.organization_id == root, PolicyLayer.scope_type == "role",
                PolicyLayer.scope_id == member_role, PolicyLayer.effective_from.is_(None)))
            if member_layer is None:
                db.add(PolicyLayer(organization_id=root, name=f"{tenant_code} members", scope_type="role",
                                   scope_id=member_role,
                                   description="Members: the Work Shift template, one field-app session, THPL cadence.",
                                   settings=clean_settings(Scope.ROLE, MEMBER_SETTINGS), created_by_name="system:seed"))
                created["member_layer"] = True
        await db.flush()
        if created["default_layer"] or created["member_layer"]:
            await bump_epoch(db, tenant.id)
    logger.info("fieldops.seeded", tenant=tenant_code, **created)
    return {"tenant_id": tenant.id, "organization_id": root, "member_role_id": member_role, **created}


async def run_seed_fieldops(database_url: str | None = None, *, tenant_code: str | None = None) -> dict:
    """Standalone async entry point (own engine, own transaction)."""
    from app.modules.tenants.seed import _async_url

    engine = create_async_engine(_async_url(database_url or settings.DATABASE_URL), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await seed_fieldops_defaults(db, tenant_code=tenant_code or settings.COMPANY_TENANT_CODE,
                                                  timezone=settings.COMPANY_TIMEZONE)
            await db.commit()
    finally:
        await engine.dispose()
    return result


__all__ = ["MEMBER_SETTINGS", "TEMPLATE", "WORK_SHIFT", "run_seed_fieldops", "seed_fieldops_defaults"]
