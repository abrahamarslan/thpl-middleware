"""Policy resolution — collect the layers that apply, order them general → specific, merge per field.

    PolicyContext ─▶ ids per dimension (dimensions.py)      ≤ 3 small indexed queries
                 ─▶ ONE query: every live layer of the context's organization ancestry whose target
                    matches one of those ids
                 ─▶ fold()  — PURE: sort, merge per setting field over the code defaults, honour locks
                 ─▶ Resolved {values, flat, provenance, conflicts, layers, epoch}

Precedence (a total order; later wins)::

    scope rank (organization 0 · role 10 · team 20 · hub 30 · beat 40 · user 50)
    → organization depth (a layer written deeper in the tree beats the same scope written higher)
    → priority → effective_from (NULLs first) → id

Scope before depth: what the work IS (role, beat) is more specific than where in the org chart the
rule was written. A branch overrides HQ's delivery-agent rule by writing a delivery-agent rule (same
rank, deeper); its general default never silently overrides a fleet-wide role rule.

Locks: a layer's ``locked_keys`` (``key`` or ``key.field``) freeze those values for every layer
folded after it. A contribution that is locked, not allowed at the layer's scope, or that breaks a
group's cross-field invariant is SKIPPED and reported in ``conflicts`` — never applied, never fatal.

No Redis cache, deliberately: resolution is 3–4 indexed queries, the hot path (ping ingest, every
shift action) reads the shift's frozen snapshot instead, and a cache would need the same lookups to
build its key.
"""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldops.policy.dimensions import DIMENSIONS, PolicyContext, applicable_ids, org_ancestry
from app.modules.fieldops.policy.settings import (
    SETTINGS,
    Scope,
    defaults,
    merge_group,
    parse_scalar,
)

_MIN_TS = dt.datetime.min.replace(tzinfo=dt.UTC)


@dataclass(frozen=True, slots=True)
class LayerRow:
    id: int
    uuid: uuid_lib.UUID
    name: str
    organization_id: int
    depth: int
    scope_type: str
    scope_id: int | None
    settings: dict[str, Any]
    locked_keys: tuple[str, ...] = ()
    priority: int = 0
    effective_from: dt.datetime | None = None
    effective_until: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    @property
    def rank(self) -> int:
        return DIMENSIONS[Scope(self.scope_type)].rank

    def sort_key(self) -> tuple:
        return (self.rank, self.depth, self.priority, self.effective_from or _MIN_TS, self.id)

    def brief(self) -> dict[str, Any]:
        return {"uuid": str(self.uuid), "name": self.name, "scope_type": self.scope_type, "scope_id": self.scope_id,
                "organization_id": self.organization_id, "depth": self.depth, "priority": self.priority}


@dataclass(slots=True)
class Resolved:
    values: dict[str, Any]                       # setting key → python value
    provenance: dict[str, str] = field(default_factory=dict)   # "key" / "key.field" → layer uuid
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    layers: list[LayerRow] = field(default_factory=list)       # applied, in fold order
    epoch: int = 0
    next_change_at: dt.datetime | None = None

    @property
    def flat(self) -> dict[str, Any]:
        return flatten(self.values)

    @property
    def most_specific(self) -> LayerRow | None:
        return self.layers[-1] if self.layers else None


def flatten(values: dict[str, Any]) -> dict[str, Any]:
    """{setting key: value} → {flat name: value} (the ``EffectivePolicy`` shape)."""
    out: dict[str, Any] = {}
    for key, value in values.items():
        spec = SETTINGS.get(key)
        if spec is None:
            continue
        if spec.is_group:
            out.update(value)
        else:
            out[spec.flat] = value
    return out


def _locked(locks: dict[str, str], key: str, fld: str | None = None) -> str | None:
    return locks.get(key) or (locks.get(f"{key}.{fld}") if fld else None)


def fold(layers: list[LayerRow]) -> Resolved:
    """Merge ``layers`` (any order) over the code defaults. PURE — the whole precedence/lock contract."""
    values = defaults()
    out = Resolved(values=values)
    locks: dict[str, str] = {}
    for layer in sorted(layers, key=LayerRow.sort_key):
        scope = Scope(layer.scope_type)
        applied = False
        for key, raw in (layer.settings or {}).items():
            spec = SETTINGS.get(key)
            if spec is None:
                out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "unknown_setting"})
                continue
            if scope not in spec.scopes:
                out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "scope_not_allowed",
                                      "scope": scope.value})
                continue
            if spec.is_group:
                if not isinstance(raw, dict):
                    out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "invalid_value"})
                    continue
                partial = {}
                for fld, value in raw.items():
                    locker = _locked(locks, key, fld)
                    if locker:
                        out.conflicts.append({"layer": str(layer.uuid), "key": f"{key}.{fld}", "reason": "locked",
                                              "locked_by": locker})
                    else:
                        partial[fld] = value
                if not partial:
                    continue
                try:
                    values[key] = merge_group(spec, values[key], partial)
                except ValueError as exc:            # pydantic ValidationError is a ValueError
                    out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "invalid_combination",
                                          "detail": _short(exc)})
                    continue
                for fld in partial:
                    out.provenance[f"{key}.{fld}"] = str(layer.uuid)
                applied = True
            else:
                locker = _locked(locks, key)
                if locker:
                    out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "locked",
                                          "locked_by": locker})
                    continue
                try:
                    values[key] = parse_scalar(spec, raw)
                except ValueError as exc:
                    out.conflicts.append({"layer": str(layer.uuid), "key": key, "reason": "invalid_value",
                                          "detail": _short(exc)})
                    continue
                out.provenance[key] = str(layer.uuid)
                applied = True
        for token in layer.locked_keys or ():
            locks.setdefault(token, str(layer.uuid))
        if applied or layer.locked_keys:
            out.layers.append(layer)
    return out


def _short(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(e.get("msg", "") for e in errors())[:300]
    return str(exc)[:300]


async def epoch_of(db: AsyncSession, tenant_id: int) -> int:
    return int(await db.scalar(text("SELECT epoch FROM fieldops.policy_epochs WHERE tenant_id = :t"),
                               {"t": tenant_id}) or 0)


#: Minutes since 2020-01-01 — the epoch's floor. ``epoch = GREATEST(epoch + 1, floor)`` keeps the version
#: monotonic even when the row (or the table, in a downgrade/upgrade) is recreated; it fits a 32-bit int
#: for millennia, so Android may keep ``config_version`` as Int.
_EPOCH_FLOOR = "floor(extract(epoch FROM now() - timestamptz '2020-01-01 00:00:00+00') / 60)::bigint"


async def bump_epoch(db: AsyncSession, tenant_id: int) -> int:
    """Bump the tenant's policy version IN the caller's transaction (commits with the layer write)."""
    return int(await db.scalar(text(f"""
        INSERT INTO fieldops.policy_epochs (tenant_id, organization_id, epoch, changed_at, app_metadata)
        SELECT :t, o.id, {_EPOCH_FLOOR}, now(), '{{}}'::jsonb FROM org_management.organizations o
         WHERE o.tenant_id = :t ORDER BY o.depth, o.id LIMIT 1
        ON CONFLICT (tenant_id) DO UPDATE
           SET epoch = GREATEST(fieldops.policy_epochs.epoch + 1, {_EPOCH_FLOOR}), changed_at = now()
        RETURNING epoch
    """), {"t": tenant_id}))


async def load_layers(db: AsyncSession, ctx: PolicyContext) -> tuple[list[LayerRow], dt.datetime | None]:
    """The live layers that apply to ``ctx`` at ``ctx.at``, plus the next instant a scheduled layer starts
    or ends (cache bound / "valid until" for callers)."""
    ancestry = await org_ancestry(db, ctx)
    ids = await applicable_ids(db, ctx)
    clauses = ["l.scope_type = 'organization'"]
    params: dict[str, Any] = {"t": ctx.tenant_id, "orgs": list(ancestry)}
    for scope, scope_ids in ids.items():
        if scope is Scope.ORGANIZATION or not scope_ids:
            continue
        clauses.append(f"(l.scope_type = '{scope.value}' AND l.scope_id = ANY(CAST(:ids_{scope.value} AS bigint[])))")
        params[f"ids_{scope.value}"] = list(scope_ids)
    rows = (await db.execute(text(f"""
        SELECT l.id, l.uuid, l.name, l.organization_id, l.scope_type, l.scope_id, l.settings, l.locked_keys,
               l.priority, l.effective_from, l.effective_until, l.updated_at
          FROM fieldops.policy_layers l
         WHERE l.tenant_id = :t AND l.deleted_at IS NULL AND l.status = 'active'
           AND l.organization_id = ANY(CAST(:orgs AS bigint[]))
           AND ({' OR '.join(clauses)})
    """), params)).all()
    live: list[LayerRow] = []
    upcoming: list[dt.datetime] = []
    for r in rows:
        if r.effective_from is not None and r.effective_from > ctx.at:
            upcoming.append(r.effective_from)
            continue
        if r.effective_until is not None and r.effective_until <= ctx.at:
            continue
        if r.effective_until is not None:
            upcoming.append(r.effective_until)
        live.append(LayerRow(
            id=r.id, uuid=r.uuid, name=r.name, organization_id=r.organization_id,
            depth=ancestry.get(r.organization_id, 0), scope_type=r.scope_type, scope_id=r.scope_id,
            settings=dict(r.settings or {}), locked_keys=tuple(r.locked_keys or ()), priority=r.priority,
            effective_from=r.effective_from, effective_until=r.effective_until, updated_at=r.updated_at,
        ))
    return live, (min(upcoming) if upcoming else None)


async def resolve(db: AsyncSession, ctx: PolicyContext) -> Resolved:
    layers, next_change = await load_layers(db, ctx)
    resolved = fold(layers)
    resolved.epoch = await epoch_of(db, ctx.tenant_id)
    resolved.next_change_at = next_change
    return resolved


__all__ = ["LayerRow", "Resolved", "bump_epoch", "epoch_of", "flatten", "fold", "load_layers", "resolve"]
