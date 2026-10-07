"""Policy: what applies to THIS user (resolution) and the administration of policy layers.

Resolution is ``policy/resolver.py`` (layers merged per setting over the code defaults); this module
wraps it in :class:`EffectivePolicy` — the flat, attribute-access view every service already uses
(``policy.max_shift_hours``, ``policy.number("max_fix_accuracy_m")``) — and owns the layer writes:
validation through the settings registry, target existence through the dimension registry, lock
governance, the per-tenant epoch bump, explain and preview.

A shift freezes the effective values at its start (``policy_snapshot``, ``snapshot_version`` 2); a
policy change affects the next shift, never a running one. Version-1 snapshots (the flat
``work_policies`` shape) read back unchanged — the flat names did not change.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid as uuid_lib
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.scope import require_organization_id
from app.modules.activity.recorder import record_activity
from app.modules.fieldops.errors import FieldOpsConflict, FieldOpsNotFound, FieldOpsRuleError
from app.modules.fieldops.model import PolicyLayer
from app.modules.fieldops.policy import resolver
from app.modules.fieldops.policy.dimensions import DIMENSIONS, PolicyContext, scope_target_exists
from app.modules.fieldops.policy.resolver import LayerRow, Resolved, flatten, fold
from app.modules.fieldops.policy.settings import (
    FLAT_TO_KEY,
    SETTINGS,
    Scope,
    SettingError,
    defaults,
    validate_layer_value,
)

logger = structlog.get_logger("app.fieldops.policy")

#: Every flat policy name with its code default (the floor; also what a v1 snapshot is read against).
CODE_DEFAULTS: dict[str, Any] = flatten(defaults())
POLICY_FIELDS: tuple[str, ...] = tuple(CODE_DEFAULTS)
_TIME_FIELDS = ("earliest_start_local", "latest_end_local")
SNAPSHOT_VERSION = 2


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.time):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


class EffectivePolicy:
    """The values that apply, with attribute access: ``policy.max_shift_hours``."""

    __slots__ = ("conflicts", "epoch", "layer_uuids", "policy_id", "policy_uuid", "provenance", "values")

    def __init__(self, values: dict[str, Any], *, policy_id: int | None = None,
                 policy_uuid: uuid_lib.UUID | None = None, layer_uuids: list[str] | None = None,
                 provenance: dict[str, str] | None = None, epoch: int = 0, conflicts: list | None = None):
        self.values = {**CODE_DEFAULTS, **values}
        self.policy_id = policy_id
        self.policy_uuid = policy_uuid
        self.layer_uuids = list(layer_uuids or ())
        self.provenance = dict(provenance or {})
        self.epoch = epoch
        self.conflicts = list(conflicts or ())

    def __getattr__(self, name: str) -> Any:
        try:
            return self.values[name]
        except KeyError:
            raise AttributeError(name) from None

    def number(self, name: str) -> float:
        return float(self.values[name])

    def flat_json(self) -> dict[str, Any]:
        return {k: _jsonable(v) for k, v in self.values.items()}

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe copy for ``shifts.policy_snapshot`` (numbers as floats, times as HH:MM:SS)."""
        return {"snapshot_version": SNAPSHOT_VERSION, "policy_id": self.policy_id,
                "policy_uuid": str(self.policy_uuid) if self.policy_uuid else None,
                "layers": self.layer_uuids, "epoch": self.epoch, "provenance": self.provenance,
                **self.flat_json()}

    @classmethod
    def from_resolved(cls, resolved: Resolved) -> EffectivePolicy:
        top = resolved.most_specific
        return cls(resolved.flat, policy_id=top.id if top else None, policy_uuid=top.uuid if top else None,
                   layer_uuids=[str(layer.uuid) for layer in resolved.layers], provenance=resolved.provenance,
                   epoch=resolved.epoch, conflicts=resolved.conflicts)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> EffectivePolicy:
        """Rebuild from a shift's frozen snapshot (unknown keys ignored, missing keys → defaults)."""
        snapshot = dict(snapshot or {})
        values = {k: snapshot[k] for k in POLICY_FIELDS if k in snapshot}
        for key in _TIME_FIELDS:
            if isinstance(values.get(key), str):
                values[key] = dt.time.fromisoformat(values[key])
        raw_uuid = snapshot.get("policy_uuid")
        return cls(values, policy_id=snapshot.get("policy_id"),
                   policy_uuid=uuid_lib.UUID(raw_uuid) if raw_uuid else None,
                   layer_uuids=snapshot.get("layers"), provenance=snapshot.get("provenance"),
                   epoch=int(snapshot.get("epoch") or 0))


async def resolve_full(db: AsyncSession, user: Any, *, shift: Any = None, at: dt.datetime | None = None,
                       identity_only: bool = False) -> Resolved:
    ctx = PolicyContext.for_user(user, at=at, shift=shift, identity_only=identity_only)
    return await resolver.resolve(db, ctx)


async def resolve_policy(db: AsyncSession, user: Any, *, shift: Any = None, at: dt.datetime | None = None,
                         identity_only: bool = False) -> EffectivePolicy:
    """What applies to ``user`` now (with ``shift``'s hub/beat as work context when given)."""
    return EffectivePolicy.from_resolved(await resolve_full(db, user, shift=shift, at=at,
                                                            identity_only=identity_only))


# ── administration ──────────────────────────────────────────────────────────────

def _uuid(ref: str) -> uuid_lib.UUID:
    try:
        return uuid_lib.UUID(str(ref))
    except ValueError:
        raise FieldOpsNotFound(f"'{ref}' is not a valid id") from None


async def get_layer(db: AsyncSession, ref: str) -> PolicyLayer:
    cond = PolicyLayer.id == int(ref) if str(ref).isdigit() else PolicyLayer.uuid == _uuid(ref)
    row = await db.scalar(select(PolicyLayer).where(cond))
    if row is None:
        raise FieldOpsNotFound(f"Policy layer '{ref}' not found")
    return row


async def list_layers(db: AsyncSession, *, scope_type: str | None = None, scope_id: int | None = None,
                      organization_id: int | None = None) -> list[PolicyLayer]:
    stmt = select(PolicyLayer)
    if scope_type is not None:
        stmt = stmt.where(PolicyLayer.scope_type == scope_type)
    if scope_id is not None:
        stmt = stmt.where(PolicyLayer.scope_id == scope_id)
    if organization_id is not None:
        stmt = stmt.where(PolicyLayer.organization_id == organization_id)
    stmt = stmt.order_by(PolicyLayer.organization_id, PolicyLayer.scope_type, PolicyLayer.scope_id.nulls_first(),
                         PolicyLayer.effective_from.nulls_first())
    return list((await db.scalars(stmt)).all())


def clean_settings(scope: Scope, settings: dict[str, Any]) -> dict[str, Any]:
    """Validate a layer's settings through the registry; refuse keys not settable at ``scope``."""
    out: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in (settings or {}).items():
        try:
            spec = SETTINGS.get(key)
            if spec is not None and scope not in spec.scopes:
                raise SettingError(key, f"cannot be set on a {scope.value} layer "
                                        f"(allowed: {', '.join(sorted(s.value for s in spec.scopes))})")
            out[key] = validate_layer_value(key, value)
        except SettingError as exc:
            errors[key] = str(exc)
    if errors:
        raise FieldOpsRuleError("invalid_policy_settings", "Some settings are invalid", data={"errors": errors})
    return out


def clean_locks(tokens: list[str] | None) -> list[str]:
    out = []
    for token in tokens or ():
        if token in SETTINGS:
            spec, ok = SETTINGS[token], True
        else:
            key, _, fld = token.rpartition(".")
            spec = SETTINGS.get(key)
            ok = spec is not None and spec.is_group and fld in spec.fields()
        if not ok or not spec.lockable:
            raise FieldOpsRuleError("invalid_lock", f"'{token}' is not a lockable setting or setting field",
                                    data={"lock": token})
        out.append(token)
    return sorted(set(out))


async def _check_target(db: AsyncSession, scope: Scope, scope_id: int | None, tenant_id: int) -> None:
    if scope is Scope.ORGANIZATION:
        if scope_id is not None:
            raise FieldOpsRuleError("invalid_scope", "An organization layer has no scope_id")
        return
    if scope_id is None:
        raise FieldOpsRuleError("invalid_scope", f"A {scope.value} layer needs scope_id")
    if not DIMENSIONS[scope].available:
        raise FieldOpsRuleError("scope_not_available", f"{scope.value} layers are not available yet",
                                data={"scope_type": scope.value})
    if not await scope_target_exists(db, scope, scope_id, tenant_id):
        raise FieldOpsRuleError("scope_target_not_found", f"{scope.value} {scope_id} not found",
                                data={"scope_type": scope.value, "scope_id": scope_id})


async def _ancestor_org_layers(db: AsyncSession, tenant_id: int, organization_id: int,
                               exclude_id: int | None = None) -> list[LayerRow]:
    rows = (await db.execute(text("""
        SELECT l.id, l.uuid, l.name, l.organization_id, o.depth, l.scope_type, l.scope_id, l.settings,
               l.locked_keys, l.priority, l.effective_from, l.effective_until
          FROM fieldops.policy_layers l
          JOIN org_management.organizations o ON o.id = l.organization_id
          JOIN org_management.organizations home ON home.id = :org
         WHERE l.tenant_id = :t AND l.deleted_at IS NULL AND l.status = 'active'
           AND l.scope_type = 'organization' AND home.hierarchy_path LIKE o.hierarchy_path || '%'
           AND (CAST(:ex AS bigint) IS NULL OR l.id <> :ex)
    """), {"t": tenant_id, "org": organization_id, "ex": exclude_id})).all()
    return [LayerRow(id=r.id, uuid=r.uuid, name=r.name, organization_id=r.organization_id, depth=int(r.depth or 0),
                     scope_type=r.scope_type, scope_id=r.scope_id, settings=dict(r.settings or {}),
                     locked_keys=tuple(r.locked_keys or ()), priority=r.priority, effective_from=r.effective_from,
                     effective_until=r.effective_until) for r in rows]


async def _check_locks_and_preview(db: AsyncSession, layer: PolicyLayer, depth: int) -> list[dict]:
    """Refuse a write that sets a key locked by an organization layer above it; return fold warnings
    (invalid combinations) of this layer over its organization chain."""
    chain = await _ancestor_org_layers(db, layer.tenant_id, layer.organization_id, exclude_id=layer.id)
    me = LayerRow(id=layer.id or 2**62, uuid=layer.uuid or uuid_lib.uuid4(), name=layer.name,
                  organization_id=layer.organization_id, depth=depth, scope_type=layer.scope_type,
                  scope_id=layer.scope_id, settings=layer.settings, locked_keys=tuple(layer.locked_keys or ()),
                  priority=layer.priority, effective_from=layer.effective_from)
    above = [r for r in chain if r.sort_key() < me.sort_key()]
    locks: dict[str, str] = {}
    for row in sorted(above, key=LayerRow.sort_key):
        for token in row.locked_keys:
            locks.setdefault(token, f"{row.name} ({row.uuid})")
    blocked = []
    for key, value in (layer.settings or {}).items():
        if key in locks:
            blocked.append({"setting": key, "locked_by": locks[key]})
        elif isinstance(value, dict):
            blocked += [{"setting": f"{key}.{f}", "locked_by": locks[f"{key}.{f}"]} for f in value
                        if f"{key}.{f}" in locks]
    if blocked:
        raise FieldOpsRuleError("policy_setting_locked", "A layer above this one locks some of these settings",
                                data={"locked": blocked})
    folded = fold(above + [me])
    return [c for c in folded.conflicts if c["layer"] == str(me.uuid)]


async def _depth(db: AsyncSession, organization_id: int) -> int:
    return int(await db.scalar(text("SELECT depth FROM org_management.organizations WHERE id = :id"),
                               {"id": organization_id}) or 0)


async def create_layer(db: AsyncSession, body: Any, *, actor: Any) -> tuple[PolicyLayer, list[dict]]:
    organization_id = await require_organization_id(db)
    scope = Scope(body.scope_type)
    tenant_id = actor.tenant_id
    await _check_target(db, scope, body.scope_id, tenant_id)
    duplicate = await db.scalar(select(PolicyLayer.id).where(
        PolicyLayer.organization_id == organization_id, PolicyLayer.scope_type == scope.value,
        func.coalesce(PolicyLayer.scope_id, 0) == (body.scope_id or 0),
        PolicyLayer.effective_from.is_(None) if body.effective_from is None
        else PolicyLayer.effective_from == body.effective_from))
    if duplicate:
        raise FieldOpsConflict("policy_layer_exists",
                               "This organization already has a layer for that target; update it instead",
                               data={"scope_type": scope.value, "scope_id": body.scope_id})
    layer = PolicyLayer(
        organization_id=organization_id, name=body.name, description=body.description, scope_type=scope.value,
        scope_id=body.scope_id, settings=clean_settings(scope, body.settings), locked_keys=clean_locks(body.locked_keys),
        priority=body.priority, effective_from=body.effective_from, effective_until=body.effective_until,
        status=body.status,
    )
    layer.tenant_id = tenant_id
    warnings = await _check_locks_and_preview(db, layer, await _depth(db, organization_id))
    db.add(layer)
    await db.flush()                     # uq_policy_layers_target_live backs the duplicate check
    epoch = await resolver.bump_epoch(db, tenant_id)
    await record_activity(db, action="fieldops_policy_layer_created", actor_id=actor.id, subject_type="PolicyLayer",
                          subject_id=layer.id, context={"scope": scope.value, "scope_id": body.scope_id,
                                                        "keys": sorted(layer.settings), "epoch": epoch})
    logger.info("fieldops.policy_layer_created", layer_id=layer.id, scope=scope.value, epoch=epoch)
    return layer, warnings


async def update_layer(db: AsyncSession, ref: str, body: Any, *, actor: Any) -> tuple[PolicyLayer, list[dict]]:
    layer = await get_layer(db, ref)
    if layer.row_version != body.row_version:
        raise FieldOpsConflict("row_version_conflict", "The layer changed since you loaded it; reload and retry",
                               data={"current_row_version": layer.row_version})
    scope = Scope(layer.scope_type)
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "settings", "unset", "locked_keys"})
    settings = dict(layer.settings or {})
    if body.settings is not None:
        settings.update(clean_settings(scope, body.settings))
    for key in body.unset or ():
        if "." in key and key not in SETTINGS:
            group, _, fld = key.rpartition(".")
            if isinstance(settings.get(group), dict):
                settings[group] = {k: v for k, v in settings[group].items() if k != fld}
                if not settings[group]:
                    settings.pop(group)
        else:
            settings.pop(key, None)
    layer.settings = settings
    if body.locked_keys is not None:
        layer.locked_keys = clean_locks(body.locked_keys)
    for key, value in changes.items():
        setattr(layer, key, value)
    warnings = await _check_locks_and_preview(db, layer, await _depth(db, layer.organization_id))
    await db.flush()
    epoch = await resolver.bump_epoch(db, layer.tenant_id)
    await record_activity(db, action="fieldops_policy_layer_updated", actor_id=actor.id, subject_type="PolicyLayer",
                          subject_id=layer.id, context={"keys": sorted(settings), "epoch": epoch})
    return layer, warnings


async def delete_layer(db: AsyncSession, ref: str, *, reason: str, actor: Any) -> None:
    layer = await get_layer(db, ref)
    layer.soft_delete(reason=reason, by=actor.id)
    await db.flush()
    epoch = await resolver.bump_epoch(db, layer.tenant_id)
    await record_activity(db, action="fieldops_policy_layer_deleted", actor_id=actor.id, subject_type="PolicyLayer",
                          subject_id=layer.id, context={"reason": reason, "epoch": epoch})


async def explain(db: AsyncSession, user: Any, *, shift: Any = None, at: dt.datetime | None = None) -> dict:
    resolved = await resolve_full(db, user, shift=shift, at=at)
    return {
        "user_id": user.id, "epoch": resolved.epoch,
        "at": (at or dt.datetime.now(dt.UTC)).isoformat(),
        "shift_uuid": str(shift.uuid) if shift is not None else None,
        "values": {k: _jsonable(v) for k, v in resolved.values.items()},
        "provenance": resolved.provenance, "conflicts": resolved.conflicts,
        "layers": [layer.brief() for layer in resolved.layers],
        "next_change_at": resolved.next_change_at.isoformat() if resolved.next_change_at else None,
    }


async def preview(db: AsyncSession, draft: Any, *, actor: Any, replace_ref: str | None = None,
                  limit: int = 200) -> dict:
    """Dry run: which users of the draft's organization subtree would see different values, per field.
    Nothing is written. At most ``limit`` users are evaluated (``sampled`` says when there were more)."""
    from app.modules.users.model import User

    organization_id = await require_organization_id(db)
    scope = Scope(draft.scope_type)
    settings = clean_settings(scope, draft.settings)
    replaced = await get_layer(db, replace_ref) if replace_ref else None
    org_path = await db.scalar(text("SELECT hierarchy_path FROM org_management.organizations WHERE id = :id"),
                               {"id": organization_id})
    users = (await db.scalars(select(User).from_statement(text("""
        SELECT u.* FROM users u JOIN org_management.organizations o ON o.id = u.organization_id
         WHERE u.tenant_id = :t AND u.deleted_at IS NULL AND o.hierarchy_path LIKE :p
         ORDER BY u.id LIMIT :lim
    """)).params(t=actor.tenant_id, p=f"{org_path}%", lim=limit + 1))).all()
    sampled = len(users) > limit
    depth = await _depth(db, organization_id)
    draft_row = LayerRow(id=2**62, uuid=uuid_lib.uuid4(), name="(draft)", organization_id=organization_id,
                         depth=depth, scope_type=scope.value, scope_id=draft.scope_id, settings=settings,
                         locked_keys=tuple(clean_locks(draft.locked_keys)), priority=draft.priority)
    affected: list[dict] = []
    for user in users[:limit]:
        ctx = PolicyContext.for_user(user)
        layers, _ = await resolver.load_layers(db, ctx)
        kept = [layer for layer in layers if replaced is None or layer.id != replaced.id]
        applies = scope is Scope.ORGANIZATION or draft.scope_id in await DIMENSIONS[scope].provider(db, ctx)
        before = fold(layers).flat
        after = fold(kept + ([draft_row] if applies else [])).flat
        changed = sorted(k for k in after if _jsonable(after[k]) != _jsonable(before.get(k)))
        if changed:
            affected.append({"user_id": user.id, "name": user.name, "changed": changed})
    return {"evaluated": min(len(users), limit), "sampled": sampled, "affected_count": len(affected),
            "affected": affected[:100]}


async def client_config(db: AsyncSession, user: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """The field app's configuration (Android ``LocationConfig`` v5) and its provenance meta.

    With an open shift: the shift's hub/beat are the work context, and FROZEN settings come from the
    shift's snapshot (a running shift keeps the obligations it started under). ``config_version`` is
    the tenant's policy epoch — monotonic whichever layer wins."""
    from app.modules.fieldops.policy.render import effective_flat, render
    from app.modules.fieldops.service.common import open_shift_of

    shift = await open_shift_of(db, user.id)
    resolved = await resolve_full(db, user, shift=shift)
    frozen = EffectivePolicy.from_snapshot(shift.policy_snapshot).values if shift is not None else None
    stamps = [t for layer in resolved.layers for t in (layer.effective_from, layer.updated_at) if t is not None]
    body = render(effective_flat(resolved.flat, frozen), config_version=resolved.epoch,
                  effective_from=max(stamps) if stamps else None,
                  auto_close_at=getattr(shift, "auto_close_at", None) if shift is not None else None,
                  planned_end_at=shift.planned_end_at if shift is not None else None)
    meta = {"shift_uuid": str(shift.uuid) if shift is not None else None,
            "layers": [layer.brief() for layer in resolved.layers],
            "valid_until": resolved.next_change_at.isoformat() if resolved.next_change_at else None}
    return body, meta


def setting_key_of(flat_name: str) -> str | None:
    return FLAT_TO_KEY.get(flat_name)


__all__ = [
    "CODE_DEFAULTS", "POLICY_FIELDS", "EffectivePolicy", "create_layer", "delete_layer", "explain", "get_layer",
    "list_layers", "preview", "resolve_full", "resolve_policy", "update_layer",
]
