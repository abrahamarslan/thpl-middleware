"""Work policies: resolution (what applies to THIS user) and administration.

Resolution::

    user → base role (users.role_id) + home organization (users.organization_id)
    for org in [home, parent, …, root]                         nearest first
        a live, active policy for (org, the user's role)  → it
        a live, active policy for (org, NULL role)        → it
    none → the code defaults (the model's column defaults)

Base role ONLY, deliberately: a contextual grant ("acting team manager in branch B") changes
what a person may do, never what they must do. One indexed query; the shift freezes the
result (``policy_snapshot``) so a mid-day policy change affects the next shift, not this one.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError
from app.database.scope import require_organization_id
from app.modules.fieldops.errors import FieldOpsNotFound, FieldOpsRuleError
from app.modules.fieldops.model import WorkPolicy
from app.modules.fieldops.schema import PolicyIn, PolicyUpdate

#: The policy columns (everything a policy decides — not identity, audit or tenancy).
POLICY_FIELDS: tuple[str, ...] = (
    "requires_shift", "allow_visits_without_shift", "require_location_consent", "require_start_selfie",
    "require_odometer", "require_start_at_place_id", "earliest_start_local", "latest_end_local",
    "max_shift_hours", "auto_close_grace_minutes", "stale_shift_after_minutes", "max_pause_minutes",
    "max_pauses_per_shift", "paid_pause_types", "track_during_pause", "tracking_mode", "ping_interval_s",
    "stationary_interval_s", "ping_min_distance_m", "geofence_enforcement", "default_visit_radius_m",
    "geocoded_radius_factor", "max_fix_accuracy_m", "allow_manual_location", "min_visit_minutes",
    "late_task_window_hours", "gap_flag_minutes", "clock_skew_flag_seconds", "min_tracking_coverage_pct",
)


def _defaults() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in POLICY_FIELDS:
        default = WorkPolicy.__table__.c[name].default
        if default is None:
            out[name] = None
        elif default.is_callable:
            out[name] = default.arg(None)
        else:
            out[name] = default.arg
    return out


CODE_DEFAULTS: dict[str, Any] = _defaults()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return list(value)
    return value


class EffectivePolicy:
    """The values that apply, with attribute access: ``policy.max_shift_hours``."""

    __slots__ = ("policy_id", "policy_uuid", "values")

    def __init__(self, values: dict[str, Any], *, policy_id: int | None = None,
                 policy_uuid: uuid_lib.UUID | None = None):
        self.values = {**CODE_DEFAULTS, **values}
        self.policy_id = policy_id
        self.policy_uuid = policy_uuid

    def __getattr__(self, name: str) -> Any:
        try:
            return self.values[name]
        except KeyError:
            raise AttributeError(name) from None

    def number(self, name: str) -> float:
        return float(self.values[name])

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe copy for ``shifts.policy_snapshot`` (numbers as floats, times as HH:MM:SS)."""
        return {"policy_id": self.policy_id, "policy_uuid": str(self.policy_uuid) if self.policy_uuid else None,
                **{k: _jsonable(v) for k, v in self.values.items()}}

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> EffectivePolicy:
        """Rebuild from a shift's frozen snapshot (unknown keys ignored, missing keys → defaults)."""
        snapshot = dict(snapshot or {})
        values = {k: snapshot[k] for k in POLICY_FIELDS if k in snapshot}
        for key in ("earliest_start_local", "latest_end_local"):
            if isinstance(values.get(key), str):
                values[key] = dt.time.fromisoformat(values[key])
        raw_uuid = snapshot.get("policy_uuid")
        return cls(values, policy_id=snapshot.get("policy_id"),
                   policy_uuid=uuid_lib.UUID(raw_uuid) if raw_uuid else None)


async def resolve_policy(db: AsyncSession, user: Any) -> EffectivePolicy:
    row = await db.scalar(
        select(WorkPolicy)
        .from_statement(text("""
            SELECT p.* FROM fieldops.work_policies p
              JOIN org_management.organizations o ON o.id = p.organization_id AND o.tenant_id = p.tenant_id
              JOIN org_management.organizations home ON home.id = :org AND home.tenant_id = :tenant
             WHERE p.tenant_id = :tenant AND p.deleted_at IS NULL AND p.status = 'active'
               AND home.hierarchy_path LIKE o.hierarchy_path || '%'
               AND (p.role_id = :role OR p.role_id IS NULL)
             ORDER BY o.depth DESC, (p.role_id IS NOT NULL) DESC
             LIMIT 1
        """))
        .params(tenant=user.tenant_id, org=user.organization_id, role=user.role_id or 0)
    )
    if row is None:
        return EffectivePolicy({})
    return EffectivePolicy({name: getattr(row, name) for name in POLICY_FIELDS},
                           policy_id=row.id, policy_uuid=row.uuid)


# ── administration ──────────────────────────────────────────────────────────────

async def get_policy(db: AsyncSession, ref: str) -> WorkPolicy:
    cond = WorkPolicy.id == int(ref) if str(ref).isdigit() else WorkPolicy.uuid == _uuid(ref)
    row = await db.scalar(select(WorkPolicy).where(cond))
    if row is None:
        raise FieldOpsNotFound(f"Work policy '{ref}' not found")
    return row


def _uuid(ref: str) -> uuid_lib.UUID:
    try:
        return uuid_lib.UUID(str(ref))
    except ValueError:
        raise FieldOpsNotFound(f"'{ref}' is not a valid id") from None


async def list_policies(db: AsyncSession) -> list[WorkPolicy]:
    return list((await db.scalars(select(WorkPolicy).order_by(WorkPolicy.organization_id,
                                                              WorkPolicy.role_id.nulls_first()))).all())


async def _check_role(db: AsyncSession, role_id: int | None, organization_id: int) -> None:
    if role_id is None:
        return
    found = await db.scalar(text("SELECT 1 FROM roles WHERE id = :id AND deleted_at IS NULL"), {"id": role_id})
    if not found:
        raise FieldOpsRuleError("role_not_found", f"Role {role_id} does not exist in this tenant")


async def create_policy(db: AsyncSession, body: PolicyIn) -> WorkPolicy:
    organization_id = await require_organization_id(db)
    await _check_role(db, body.role_id, organization_id)
    role_match = WorkPolicy.role_id.is_(None) if body.role_id is None else WorkPolicy.role_id == body.role_id
    if await db.scalar(select(WorkPolicy.id).where(WorkPolicy.organization_id == organization_id, role_match)):
        raise ConflictError("This organization already has a policy for that role; update it instead",
                            data={"role_id": body.role_id})
    data = body.model_dump()
    data["paid_pause_types"] = [p.value if hasattr(p, "value") else p for p in data["paid_pause_types"]]
    row = WorkPolicy(organization_id=organization_id, **{k: (v.value if hasattr(v, "value") else v)
                                                         for k, v in data.items()})
    db.add(row)
    await db.flush()          # uq_work_policies_target_live backs the check above against a race
    return row


async def update_policy(db: AsyncSession, ref: str, body: PolicyUpdate) -> WorkPolicy:
    row = await get_policy(db, ref)
    if row.row_version != body.row_version:
        raise ConflictError("The policy changed since you loaded it; reload and retry",
                            data={"current_row_version": row.row_version})
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    if "role_id" in changes:
        await _check_role(db, changes["role_id"], row.organization_id)
    for key, value in changes.items():
        if key == "paid_pause_types":
            value = [p.value if hasattr(p, "value") else p for p in value]
        setattr(row, key, value.value if hasattr(value, "value") else value)
    await db.flush()
    return row


async def delete_policy(db: AsyncSession, ref: str, *, reason: str, actor_id: int) -> None:
    row = await get_policy(db, ref)
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()


__all__ = [
    "CODE_DEFAULTS", "POLICY_FIELDS", "EffectivePolicy",
    "create_policy", "delete_policy", "get_policy", "list_policies", "resolve_policy", "update_policy",
]
