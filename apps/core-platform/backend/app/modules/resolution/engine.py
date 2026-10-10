"""The resolution engine — "what applies here?", for any facet, for many subjects at once.

    resolve_many(db, "account", "sales_line", subjects)        → one Resolution per subject

Cost is a FIXED number of statements, whatever the number of subjects:

    1  the effective policy overrides for the subjects' organizations (skipped when a policy is given)
    +1 per expansion the policy declares (an item → its categories)
    +   the facet's ``load`` (2–3 for taxes / accounts: candidates, defaults, usability)

Everything after that is pure and in memory. ``tests/test_resolution.py`` asserts the
statement count for 1, 50 and 500 subjects.

Rules that make it safe (docs/implementation-plan/accounts-module.md §7.6):

  * **first step that answers wins**; within a role holding several owners (an item in two
    categories) the first owner that answers wins, in the order the expander returned;
  * **fail closed**: a step whose answer is unusable (an inactive account, a deleted tax)
    returns ``Outcome.UNUSABLE`` naming owner and reason — unless the step says ``skip``.
    Falling through silently would post revenue to the wrong account;
  * **pending never answers**: a source-named value we have not synced is shown in the trace
    as ``pending`` and the walk continues;
  * **deterministic**: ties inside a step are the facet's ``select`` (position, id);
  * **no guessing**: nothing anywhere → ``Outcome.NONE``; the caller decides (a draft shows
    "unassigned", issuing a document refuses).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError
from app.modules.resolution.model import ResolutionPolicyOverride
from app.modules.resolution.registry import resolution_registry
from app.modules.resolution.types import (
    ORGANIZATION_ROLE,
    Outcome,
    OwnerRef,
    Policy,
    Resolution,
    Step,
    Subject,
    TraceEntry,
)

logger = structlog.get_logger("app.resolution.engine")


class ResolutionError(AppError):
    status_code = 422
    code = "resolution_error"


def steps_from_json(raw: Sequence[dict[str, Any]]) -> list[Step]:
    return [Step(role=str(item["role"]), filter=item.get("filter"), on_unusable=item.get("on_unusable") or "fail")
            for item in raw]


async def effective_policies(
    db: AsyncSession, facet: str, subject: str, organization_ids: set[int | None],
) -> dict[int | None, Policy]:
    """The policy each organization runs: its own override → the tenant's → the code default.

    ONE query. The tenancy filter scopes it to the current tenant; ``organization_id`` NULL
    rows are the tenant-wide overrides.
    """
    default = resolution_registry.policy(facet, subject)
    orgs = {o for o in organization_ids if o is not None}
    scope = ResolutionPolicyOverride.organization_id.is_(None)
    if orgs:
        scope = or_(scope, ResolutionPolicyOverride.organization_id.in_(orgs))
    rows = (await db.scalars(select(ResolutionPolicyOverride).where(
        ResolutionPolicyOverride.facet == facet, ResolutionPolicyOverride.subject == subject, scope,
    ))).all()
    tenant_row = next((r for r in rows if r.organization_id is None), None)
    by_org = {r.organization_id: r for r in rows if r.organization_id is not None}

    def build(row: ResolutionPolicyOverride | None, layer: str) -> Policy:
        if row is None:
            return default
        return default.with_steps(steps_from_json(row.steps), use_organization_default=row.use_organization_default,
                                  layer=layer)

    result: dict[int | None, Policy] = {}
    for org in organization_ids:
        if org is not None and org in by_org:
            result[org] = build(by_org[org], "organization")
        else:
            result[org] = build(tenant_row, "tenant")
    return result


async def resolve_many(
    db: AsyncSession,
    facet_code: str,
    subject_kind: str,
    subjects: Sequence[Subject],
    *,
    policy: Policy | None = None,
    explain: bool = False,
) -> list[Resolution]:
    """Resolve ``subjects`` under the effective policy (or the ``policy`` given)."""
    if not subjects:
        return []
    facet = resolution_registry.facet(facet_code)
    for index, subject in enumerate(subjects):
        try:
            subject.context = facet.context(subject.context)
        except ValidationError as exc:
            raise ResolutionError(f"subject {index}: invalid {facet_code} context",
                                  data={"errors": exc.errors(include_url=False, include_context=False)}) from exc

    if policy is not None:
        problems = resolution_registry.problems_of(policy)
        if problems:
            raise ResolutionError("; ".join(problems))
        policies = {s.organization_id: policy for s in subjects}
    else:
        policies = await effective_policies(db, facet_code, subject_kind, {s.organization_id for s in subjects})

    # Unknown roles are a caller bug — refuse loudly rather than ignore a supplied owner.
    for index, subject in enumerate(subjects):
        known = policies[subject.organization_id].all_roles
        unknown = sorted(set(subject.roles) - known)
        if unknown:
            raise ResolutionError(f"subject {index}: unknown role(s) {unknown} for {facet_code}/{subject_kind} "
                                  f"(known: {sorted(known)})")

    # ── expansions: one batched call per expansion ─────────────────────────────
    expanded: list[dict[str, list[OwnerRef]]] = [dict() for _ in subjects]
    seen_expansions = {e for p in policies.values() for e in p.expansions}
    for expansion in seen_expansions:
        sources = {owner for s in subjects for owner in s.owners_of(expansion.from_role)}
        if not sources:
            continue
        mapping = await resolution_registry.expander(expansion.expander)(db, sources)
        for index, subject in enumerate(subjects):
            if expansion not in policies[subject.organization_id].expansions or expansion.role in subject.roles:
                continue          # a caller-supplied value for the derived role wins
            derived: list[OwnerRef] = []
            for owner in subject.owners_of(expansion.from_role):
                for target in mapping.get(owner, []):
                    if target not in derived:
                        derived.append(target)
            expanded[index][expansion.role] = derived

    def owners(index: int, role: str) -> list[OwnerRef]:
        if role in expanded[index]:
            return expanded[index][role]
        return subjects[index].owners_of(role)

    every_owner = {
        owner
        for index, subject in enumerate(subjects)
        for step in policies[subject.organization_id].steps
        for owner in owners(index, step.role)
    }
    data = await facet.load(db, every_owner, subjects)

    results: list[Resolution] = []
    for index, subject in enumerate(subjects):
        results.append(_walk(facet, data, policies[subject.organization_id], subject,
                             lambda role, i=index: owners(i, role), explain))
    return results


def _walk(facet, data, policy: Policy, subject: Subject, owners_of, explain: bool) -> Resolution:
    trace: list[TraceEntry] = []

    def note(entry: TraceEntry) -> None:
        if explain:
            trace.append(entry)

    for number, step in enumerate(policy.steps):
        candidates_owners = owners_of(step.role)
        if not candidates_owners:
            note(TraceEntry(number, step.role, None, "no_owner"))
            continue
        for owner in candidates_owners:
            carried = list(data.candidates(owner))
            candidates = carried
            if step.filter is not None:
                keep = facet.filters[step.filter]
                candidates = [c for c in candidates if keep(c)]
            chosen = facet.select(candidates, subject.context)
            if not chosen:
                if data.has_pending(owner):
                    note(TraceEntry(number, step.role, owner, "pending"))
                else:
                    note(TraceEntry(number, step.role, owner, "filtered" if carried else "no_candidates"))
                continue
            reasons = [r for r in (data.unusable(c, subject.organization_id) for c in chosen) if r]
            if reasons:
                if step.on_unusable == "skip":
                    note(TraceEntry(number, step.role, owner, f"skipped:{reasons[0]}"))
                    continue
                note(TraceEntry(number, step.role, owner, f"unusable:{reasons[0]}"))
                return Resolution(Outcome.UNUSABLE, values=chosen, via=step.role, owner=owner,
                                  reason=reasons[0], trace=trace)
            note(TraceEntry(number, step.role, owner, "answered"))
            return Resolution(Outcome.ANSWERED, values=chosen, via=step.role, owner=owner, trace=trace)

    if policy.use_organization_default:
        defaults = list(data.organization_default(subject.organization_id, subject.context))
        org_ref = OwnerRef("organization", subject.organization_id) if subject.organization_id else None
        if defaults:
            reasons = [r for r in (data.unusable(c, subject.organization_id) for c in defaults) if r]
            if reasons:
                note(TraceEntry(None, ORGANIZATION_ROLE, org_ref, f"unusable:{reasons[0]}"))
                return Resolution(Outcome.UNUSABLE, values=defaults, via=ORGANIZATION_ROLE, owner=org_ref,
                                  reason=reasons[0], trace=trace)
            note(TraceEntry(None, ORGANIZATION_ROLE, org_ref, "answered"))
            return Resolution(Outcome.ORGANIZATION_DEFAULT, values=defaults, via=ORGANIZATION_ROLE,
                              owner=org_ref, trace=trace)
        note(TraceEntry(None, ORGANIZATION_ROLE, org_ref, "no_candidates"))
    return Resolution(Outcome.NONE, trace=trace)


async def resolve_one(
    db: AsyncSession, facet_code: str, subject_kind: str, subject: Subject, *,
    policy: Policy | None = None, explain: bool = False,
) -> Resolution:
    (result,) = await resolve_many(db, facet_code, subject_kind, [subject], policy=policy, explain=explain)
    return result


__all__ = ["ResolutionError", "effective_policies", "resolve_many", "resolve_one", "steps_from_json"]
