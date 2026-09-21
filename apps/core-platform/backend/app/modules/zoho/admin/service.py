"""Operator actions for the Zoho integration (service layer).

Every mutation is (a) validated, (b) written through the component that owns
it (switches → settings audit log; policies → their table), and (c) recorded
in ``activity_logs`` with the operator and their stated reason.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, NotFoundError
from app.database.redis import redis_client
from app.modules.activity.recorder import record_activity
from app.modules.users.model import User
from app.modules.zoho.admin import crud
from app.modules.zoho.control.planner import HEALTH_KEY, LANE_MANUAL
from app.modules.zoho.control.runs import running_count
from app.modules.zoho.control.switches import DURABLE_SWITCHES, zoho_switches
from app.modules.zoho.core.auth import zoho_token_manager
from app.modules.zoho.core.breaker import zoho_breaker
from app.modules.zoho.core.governor import zoho_governor

logger = structlog.get_logger("app.zoho.admin")


async def _breaker_groups() -> list[str]:
    groups: set[str] = set()
    try:
        async for key in redis_client.scan_iter(match="zoho:cb:*:meta", count=200):
            groups.add(key.split(":", 2)[2].rsplit(":", 1)[0])
    except RedisError:
        pass
    return sorted(groups)


async def health(db: AsyncSession) -> dict[str, Any]:
    planner = None
    try:
        raw = await redis_client.get(HEALTH_KEY)
        planner = json.loads(raw).get("planner") if raw else None
    except (RedisError, ValueError):
        planner = None
    return {
        "governor": await zoho_governor.snapshot(),
        "switches": (await zoho_switches.snapshot()).as_dict(),
        "token": await zoho_token_manager.health(),
        "breakers": [await zoho_breaker.snapshot(group) for group in await _breaker_groups()],
        "planner": planner,
        "running_runs": await running_count(db),
    }


async def set_switch(
    db: AsyncSession, name: str, value: Any, *, operator: User, reason: str, ip: str | None
) -> dict[str, Any]:
    if name not in DURABLE_SWITCHES:
        raise NotFoundError(f"Unknown switch '{name}'")
    try:
        state = await zoho_switches.set(db, name, value, actor=str(operator.id), ip_address=ip)
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    await record_activity(
        db, action="zoho_switch_changed", actor_id=operator.id,
        subject_type="ZohoIntegration", subject_id=name,
        description=f"Set Zoho switch {name}={value}", context={"reason": reason, "value": value},
    )
    return state.as_dict()


async def pause_module(db: AsyncSession, module: str, *, pause: bool, operator: User,
                       reason: str, ip: str | None) -> dict[str, Any]:
    _require_module(module)
    current = set((await zoho_switches.snapshot()).paused_modules)
    updated = (current | {module}) if pause else (current - {module})
    state = await zoho_switches.set(db, "paused_modules", sorted(updated), actor=str(operator.id), ip_address=ip)
    await record_activity(
        db, action="zoho_module_paused" if pause else "zoho_module_resumed", actor_id=operator.id,
        subject_type="ZohoModule", subject_id=module, context={"reason": reason},
    )
    return state.as_dict()


def _require_module(module: str) -> None:
    from app.modules.zoho.sync.registry import sync_registry

    sync_registry.get(module)            # raises NotFoundError for unknown modules


async def request_run(db: AsyncSession, module: str, *, mode: str | None, operator: User,
                      reason: str | None) -> dict[str, Any]:
    _require_module(module)
    from app.tasks.zoho_sync import sync_module_run

    result = sync_module_run.delay(module, LANE_MANUAL, mode, "operator", operator.id)
    await record_activity(
        db, action="zoho_run_requested", actor_id=operator.id,
        subject_type="ZohoModule", subject_id=module,
        context={"mode": mode, "reason": reason, "task_id": result.id},
    )
    return {"module": module, "lane": LANE_MANUAL, "mode": mode, "task_id": result.id}


async def get_run(db: AsyncSession, run_id: uuid.UUID):
    run = await crud.get_run(db, run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    return run


async def record_history(db: AsyncSession, module: str, ref: str, *, by: str, event_type: str | None,
                         limit: int):
    _require_module(module)
    if by == "local":
        if not ref.isdigit():
            raise AppError("local ids are numeric; use ?by=zoho for Zoho ids")
        return await crud.record_events(db, module=module, local_id=int(ref), event_type=event_type, limit=limit)
    return await crud.record_events(db, module=module, zoho_id=ref, event_type=event_type, limit=limit)


async def update_policy(db: AsyncSession, policy_id: int, *, keep_days: int, enabled: bool,
                        operator: User, reason: str):
    policy = await crud.get_policy(db, policy_id)
    if policy is None:
        raise NotFoundError(f"Retention policy {policy_id} not found")
    if policy.event_class == "approval" and keep_days < 365:
        raise AppError("approval history must be kept for at least 365 days")
    before = {"keep_days": policy.keep_days, "enabled": policy.enabled}
    policy.keep_days, policy.enabled, policy.updated_by = keep_days, enabled, operator.id
    await db.flush()
    await record_activity(
        db, action="zoho_retention_changed", actor_id=operator.id,
        subject_type="ZohoRetentionPolicy", subject_id=policy_id,
        changes={"before": before, "after": {"keep_days": keep_days, "enabled": enabled}},
        context={"reason": reason, "table": policy.table_name, "scope": f"{policy.module}/{policy.event_class}"},
    )
    return policy


async def reset_breaker(group: str, *, operator: User, db: AsyncSession) -> dict[str, Any]:
    await zoho_breaker.reset(group)
    await record_activity(
        db, action="zoho_breaker_reset", actor_id=operator.id, subject_type="ZohoBreaker", subject_id=group,
    )
    return await zoho_breaker.snapshot(group)


# ── runtime module configuration (control/config.py) ───────────────────────

async def module_config(db: AsyncSession, module: str) -> dict[str, Any]:
    from app.modules.zoho.control.config import zoho_config
    from app.modules.zoho.sync.registry import sync_registry

    defn = sync_registry.get(module)
    return {"module": module, "knobs": await zoho_config.describe(db, defn)}


async def set_module_config(db: AsyncSession, module: str, knob: str, value: Any, *, operator: User,
                            reason: str, ip: str | None) -> dict[str, Any]:
    from app.modules.zoho.control.config import ConfigError, zoho_config
    from app.modules.zoho.sync.registry import sync_registry

    defn = sync_registry.get(module)
    before = (await zoho_config.describe(db, defn)).get(knob, {}).get("value")
    try:
        stored = await zoho_config.set(db, defn, knob, value, actor=str(operator.id), ip_address=ip)
    except ConfigError as exc:
        raise AppError(str(exc)) from exc
    await record_activity(
        db, action="zoho_config_changed", actor_id=operator.id, subject_type="ZohoModule", subject_id=module,
        changes={"before": {knob: before}, "after": {knob: stored}}, context={"reason": reason, "knob": knob},
    )
    return await module_config(db, module)


async def clear_module_config(db: AsyncSession, module: str, knob: str, *, operator: User, reason: str,
                              ip: str | None) -> dict[str, Any]:
    from app.modules.zoho.control.config import ConfigError, zoho_config
    from app.modules.zoho.sync.registry import sync_registry

    defn = sync_registry.get(module)
    try:
        removed = await zoho_config.clear(db, defn, knob, actor=str(operator.id), ip_address=ip)
    except ConfigError as exc:
        raise AppError(str(exc)) from exc
    if not removed:
        raise NotFoundError(f"No override for {module}.{knob}")
    await record_activity(
        db, action="zoho_config_cleared", actor_id=operator.id, subject_type="ZohoModule", subject_id=module,
        context={"reason": reason, "knob": knob},
    )
    return await module_config(db, module)
