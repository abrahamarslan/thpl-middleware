"""Tax assignments business logic — what an entity's taxes ARE, for any entity.

| Rule | Pre-flight (clean 422/409) | Database (authoritative) |
|---|---|---|
| owner class is registered AND opted in | ``_policy`` | FK ``tax_assignments → taxable_entity_types → core.entity_types`` |
| owner exists | ``_owner`` | deferred ``assert_entity_exists`` |
| owner shares the assignment's tenant/organization | ``_owner`` (uses the owner's org) | deferred ``tax.assert_owner_scope`` |
| class may carry an exemption | ``_validate`` | deferred integrity trigger |
| one tax per context unless the class allows several | ``_validate`` | deferred integrity trigger (per-owner advisory lock) |
| no duplicate tax in one context | ``_validate`` | ``uq_tax_assignments_component / _exemption / _pending`` |
| the tax exists and is the same tenant's | ``_validate`` | composite FKs to ``tax_components`` / ``tax_exemptions`` |
| the organization may USE the tax | ``_validate`` (``organization_tax_components``) | — |
| a frozen assignment never changes | ``_refuse_if_frozen`` | ``tax.guard_frozen_tax_assignment`` |
| a source's rows are not edited locally | the caller (``source_system``) | — |

One function writes assignments: :func:`replace_assignments`. The API, the
categories service and the Zoho sync hook all call it, so the checks cannot
diverge between "a person did it" and "the sync did it".

**Resolution.** :func:`resolve_taxes` answers "which tax applies here?" for a
chain of owners (a line → its item → its category …), most specific first, falling
back to the organization's default. The chain is the CALLER's policy — this module
only says what each owner carries and how a context narrows it
(:func:`select_applicable`).

**Freezing.** :func:`freeze_owner` snapshots an owner's taxes as they are now, for
a document that has been issued; the row then cannot change. Computed tax AMOUNTS
are the document module's — they need a base this module never sees.

Zero Zoho calls here. A source arrives through ``source_system`` on the write, and
an unresolvable source tax id becomes a *pending* row plus a
``sync.pending_references`` waiter that the generic reconcile lane links.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.database import scope
from app.modules.activity.recorder import record_activity
from app.modules.sync.models import PendingReference
from app.modules.taxes import assignment_crud as crud
from app.modules.taxes import crud as tax_crud
from app.modules.taxes.assignment import TaxableEntityType, TaxAssignment
from app.modules.taxes.assignment_schema import TaxAssignmentItem
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.enums import TaxSpecification, TaxTransactionType

logger = structlog.get_logger("app.taxes.assignments")

#: The source-side module that owns the taxes a pending assignment waits for.
_PENDING_MODULE = "taxes"
_PENDING_TABLE = "tax.tax_assignments"
_PENDING_COLUMN = "tax_component_id"


class TaxRuleError(AppError):
    status_code = 422
    code = "tax_rule_violation"


# ── the write model ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    """One desired assignment: WHAT (a tax, an exemption, or a source's pending tax id)
    and WHEN (inter/intra × sales/purchase; ``None`` = any)."""

    tax_component_id: int | None = None
    tax_exemption_id: int | None = None
    external_ref: str | None = None
    tax_specification: str | None = None
    transaction_type: str | None = None
    position: int = 0

    @property
    def key(self) -> tuple[str, Any, str | None, str | None]:
        return _key(self.tax_component_id, self.tax_exemption_id, self.external_ref,
                    self.tax_specification, self.transaction_type)

    @property
    def context(self) -> tuple[str | None, str | None]:
        return self.tax_specification, self.transaction_type


def _key(component_id, exemption_id, external_ref, specification, transaction_type):
    if component_id is not None:
        kind, target = "component", component_id
    elif exemption_id is not None:
        kind, target = "exemption", exemption_id
    else:
        kind, target = "pending", external_ref
    return kind, target, specification, transaction_type


def _row_key(row: TaxAssignment) -> tuple[str, Any, str | None, str | None]:
    return _key(row.tax_component_id, row.tax_exemption_id, row.external_ref,
                row.tax_specification, row.transaction_type)


# ── resolution (pure) ─────────────────────────────────────────────────────────

def select_applicable(
    rows: Iterable[Any], *, specification: str | None, transaction_type: str | None,
) -> list[Any]:
    """The rows of ONE owner that apply in a context — most specific level wins.

    A row applies when each of its context columns is either unset ("any") or equal
    to the context asked for. Among the applicable rows only the most specific
    level is kept (both columns set > one > none), so an owner's ``inter`` tax
    overrides its any-context tax for an inter-state sale instead of stacking on
    it. What is left at that level applies together, in ``position`` order.

    Asking with ``specification=None`` ("I do not know") matches only rows that do
    not care — never a row that names a specification.
    """
    matched: list[tuple[int, Any]] = []
    for row in rows:
        spec, txn = row.tax_specification, row.transaction_type
        if spec is not None and spec != specification:
            continue
        if txn is not None and txn != transaction_type:
            continue
        matched.append(((spec is not None) + (txn is not None), row))
    if not matched:
        return []
    best = max(level for level, _ in matched)
    kept = [row for level, row in matched if level == best]
    return sorted(kept, key=lambda row: (row.position, row.id))


# ── reads ─────────────────────────────────────────────────────────────────────

async def list_policies(db: AsyncSession) -> list[TaxableEntityType]:
    return await crud.list_policies(db)


async def list_assignments(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, include_pending: bool = True,
) -> list[TaxAssignment]:
    await _policy(db, owner_type_code, for_write=False)
    return await crud.list_for_owner(db, owner_type_code, owner_id, include_pending=include_pending)


@dataclass(slots=True)
class ResolvedTaxes:
    """The answer to "which tax applies here?"."""

    #: ``("category", 5)`` — the owner whose assignments answered; ``None`` when the
    #: organization default (or nothing) did.
    resolved_from: tuple[str, int] | None = None
    #: ``"owner"`` | ``"organization_default"`` | ``"none"``
    via: str = "none"
    assignments: list[TaxAssignment] = field(default_factory=list)
    default_components: list[TaxComponent] = field(default_factory=list)

    @property
    def components(self) -> list[TaxComponent]:
        found = [a.tax_component for a in self.assignments if a.tax_component is not None]
        return found or list(self.default_components)

    @property
    def exemptions(self) -> list[Any]:
        return [a.tax_exemption for a in self.assignments if a.tax_exemption is not None]


async def resolve_taxes(
    db: AsyncSession, owners: Sequence[tuple[str, int]], *, specification: str | None = None,
    transaction_type: str | None = None, organization_id: int | None = None,
) -> ResolvedTaxes:
    """First owner in ``owners`` whose assignments apply in this context, else the org default.

    ``owners`` is most-specific first — e.g. ``[("invoice_line", 9), ("item", 4),
    ("category", 2)]``. Pending (unresolved) rows never answer. An exemption is an
    assignment like any other: whoever carries one at the winning level returns it.

    Runs on the platform resolution engine (``app.modules.resolution``) with an ad-hoc
    policy — one step per owner, in order — so a chain of any length costs a fixed number
    of queries. Steps ``skip`` an unusable answer, which is this function's historical
    contract; document modules resolve through the engine's named, fail-closed policies.
    """
    from app.modules.resolution import Outcome, OwnerRef, Policy, Step, Subject, resolve_one

    roles = {f"owner_{index}": OwnerRef(owner_type, owner_id) for index, (owner_type, owner_id) in enumerate(owners)}
    policy = Policy(facet="tax", subject="adhoc", roles=frozenset(roles), layer="adhoc",
                    steps=tuple(Step(role, on_unusable="skip") for role in roles))
    result = await resolve_one(db, "tax", "adhoc", Subject(
        roles=roles, organization_id=organization_id,
        context={"specification": specification, "transaction_type": transaction_type},
    ), policy=policy)
    if result.outcome is Outcome.ANSWERED and result.owner is not None:
        return ResolvedTaxes(resolved_from=(result.owner.type_code, result.owner.id), via="owner",
                             assignments=list(result.values))
    if result.outcome is Outcome.ORGANIZATION_DEFAULT:
        return ResolvedTaxes(via="organization_default", default_components=list(result.values))
    return ResolvedTaxes()


# ── from the API shape to the write model ─────────────────────────────────────

async def specs_from_items(db: AsyncSession, items: Sequence[TaxAssignmentItem]) -> list[AssignmentSpec]:
    """Resolve the references in ``items`` (a tax's id / uuid / source id; an exemption's id / uuid)."""
    specs: list[AssignmentSpec] = []
    for item in items:
        component_id = exemption_id = None
        if item.tax is not None:
            component = await tax_crud.get_component_by_ref(db, item.tax)
            if component is None:
                raise TaxRuleError(f"Tax '{item.tax}' not found")
            component_id = component.id
        else:
            exemption = await crud.get_exemption_by_ref(db, item.tax_exemption)
            if exemption is None:
                raise TaxRuleError(f"Tax exemption '{item.tax_exemption}' not found")
            exemption_id = exemption.id
        specs.append(AssignmentSpec(
            tax_component_id=component_id, tax_exemption_id=exemption_id,
            tax_specification=item.tax_specification.value if item.tax_specification else None,
            transaction_type=item.transaction_type.value if item.transaction_type else None,
            position=item.position,
        ))
    return specs


# ── the one writer ─────────────────────────────────────────────────────────────

async def _policy(db: AsyncSession, owner_type_code: str, *, for_write: bool = True) -> TaxableEntityType:
    policy = await crud.get_policy(db, owner_type_code)
    if policy is None:
        raise TaxRuleError(
            f"'{owner_type_code}' cannot carry taxes: it is not opted in to tax assignments",
            data={"hint": "GET /api/taxes/assignments/taxable-types lists the classes that can"},
        )
    if for_write and not policy.is_enabled:
        raise TaxRuleError(f"Tax assignments are disabled for '{owner_type_code}'")
    return policy


async def _owner(db: AsyncSession, owner_type_code: str, owner_id: int) -> crud.OwnerInfo:
    info = await crud.owner_info(db, owner_type_code, owner_id)
    if not info.exists:
        raise NotFoundError(f"{owner_type_code} {owner_id} not found")
    return info


async def _organization(db: AsyncSession, info: crud.OwnerInfo, given: int | None) -> int:
    if given is not None:
        return given
    if info.organization_id is not None:
        return info.organization_id
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise TaxRuleError(exc.msg, data=exc.data) from exc


def _validate(
    specs: Sequence[AssignmentSpec], policy: TaxableEntityType, components: dict[int, TaxComponent],
    exemptions: dict[int, Any], granted: set[int] | None,
) -> None:
    seen: set[tuple] = set()
    per_context: dict[tuple, int] = {}
    for spec in specs:
        if spec.tax_specification is not None and spec.tax_specification not in {m.value for m in TaxSpecification}:
            raise TaxRuleError(f"Unknown tax specification '{spec.tax_specification}' (inter / intra)")
        if spec.transaction_type is not None and spec.transaction_type not in {m.value for m in TaxTransactionType}:
            raise TaxRuleError(f"Unknown transaction type '{spec.transaction_type}' (sales / purchase)")
        if sum(x is not None for x in (spec.tax_component_id, spec.tax_exemption_id, spec.external_ref)) != 1:
            raise TaxRuleError("An assignment names exactly one of: a tax, an exemption, or a source tax id")
        if spec.key in seen:
            raise TaxRuleError("The same tax is assigned twice in one context")
        seen.add(spec.key)

        if spec.tax_component_id is not None:
            if spec.tax_component_id not in components:
                raise TaxRuleError(f"Tax {spec.tax_component_id} not found")
            if granted is not None and spec.tax_component_id not in granted:
                raise TaxRuleError(
                    f"Tax '{components[spec.tax_component_id].tax_name}' is not enabled for this organization",
                    data={"hint": "GET /api/taxes?organization_id=… lists what it may use"},
                )
        if spec.tax_exemption_id is not None:
            if not policy.allows_exemption:
                raise TaxRuleError(f"'{policy.entity_type_code}' cannot carry a tax exemption")
            if spec.tax_exemption_id not in exemptions:
                raise TaxRuleError(f"Tax exemption {spec.tax_exemption_id} not found")

        if not policy.allows_multiple:
            bucket = (spec.context, spec.tax_exemption_id is not None)
            per_context[bucket] = per_context.get(bucket, 0) + 1
            if per_context[bucket] > 1:
                raise TaxRuleError(
                    f"'{policy.entity_type_code}' takes one {'exemption' if bucket[1] else 'tax'} per context "
                    f"(specification {spec.tax_specification or 'any'}, transaction {spec.transaction_type or 'any'})"
                )


async def replace_assignments(
    db: AsyncSession, owner_type_code: str, owner_id: int, specs: Sequence[AssignmentSpec], *,
    source_system: str | None = None, organization_id: int | None = None, actor_id: int | None = None,
) -> list[TaxAssignment]:
    """Make ``specs`` the complete set of taxes this ``source_system`` maintains for the owner.

    Idempotent and diff-based: rows already there are kept (position updated), rows no
    longer wanted are soft-deleted, new ones are inserted. Only rows written by the
    SAME ``source_system`` are touched (``None`` = local), so a sync never deletes what a
    person assigned and a person cannot overwrite what the sync fed. A frozen row is
    never touched — replacing an issued owner's taxes is a 409.
    """
    policy = await _policy(db, owner_type_code)
    info = await _owner(db, owner_type_code, owner_id)
    org_id = await _organization(db, info, organization_id)

    component_ids = [s.tax_component_id for s in specs if s.tax_component_id is not None]
    components = await crud.components_by_id(db, component_ids)
    exemptions = await crud.exemptions_by_id(db, [s.tax_exemption_id for s in specs if s.tax_exemption_id])
    # A source vouches for its own taxes (the sync grants what it syncs); a person is held to the grants.
    granted = await crud.granted_component_ids(db, org_id, component_ids) if source_system is None else None
    _validate(specs, policy, components, exemptions, granted)

    existing = await crud.list_for_owner(db, owner_type_code, owner_id)
    mine = [row for row in existing if row.source_system == source_system]
    if not policy.allows_multiple:
        # Another source's row occupying a context makes ours a second tax there.
        taken = {((row.tax_specification, row.transaction_type), row.tax_exemption_id is not None): row.source_system
                 for row in existing if row.source_system != source_system}
        for spec in specs:
            holder = taken.get((spec.context, spec.tax_exemption_id is not None), False)
            if holder is not False:
                raise TaxRuleError(
                    f"'{owner_type_code}' takes one tax per context and this one is already "
                    f"{'maintained by ' + holder if holder else 'assigned locally'}",
                    data={"specification": spec.tax_specification, "transaction_type": spec.transaction_type},
                )
    wanted = {spec.key: spec for spec in specs}
    doomed = [row for row in mine if _row_key(row) not in wanted]
    if any(row.is_frozen for row in doomed):
        raise ConflictError(f"{owner_type_code} {owner_id} has issued (frozen) taxes; they cannot be replaced")

    now_kept: dict[tuple, TaxAssignment] = {_row_key(row): row for row in mine if _row_key(row) in wanted}
    for row in doomed:
        row.soft_delete(reason=f"replaced ({source_system or 'local'})", by=actor_id)
        if row.is_pending:
            await _drop_waiter(db, row)
    for key, row in now_kept.items():
        spec = wanted[key]
        if row.position != spec.position:
            if row.is_frozen:
                raise ConflictError(f"{owner_type_code} {owner_id} has issued (frozen) taxes; they cannot be reordered")
            row.position = spec.position
    # The partial uniques are immediate: free the old rows before inserting their replacements.
    await db.flush()

    created: list[TaxAssignment] = []
    for key, spec in wanted.items():
        if key in now_kept:
            continue
        row = TaxAssignment(
            owner_type_code=owner_type_code, owner_id=owner_id, organization_id=org_id,
            tax_component_id=spec.tax_component_id, tax_exemption_id=spec.tax_exemption_id,
            external_ref=spec.external_ref, tax_specification=spec.tax_specification,
            transaction_type=spec.transaction_type, position=spec.position, source_system=source_system,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    for row in created:
        if row.is_pending:
            await _queue_waiter(db, row)

    await record_activity(
        db, action="tax_assignments_replaced", actor_id=actor_id, subject_type=owner_type_code,
        subject_id=str(owner_id),
        changes={"after": {"source": source_system or "local",
                           "taxes": [{"tax": s.tax_component_id or s.external_ref, "exemption": s.tax_exemption_id,
                                      "specification": s.tax_specification, "transaction": s.transaction_type}
                                     for s in specs]}},
    )
    return await crud.list_for_owner(db, owner_type_code, owner_id)


async def _queue_waiter(db: AsyncSession, row: TaxAssignment) -> None:
    """A source named a tax we have not synced: wait on the generic reconcile queue."""
    logger.info("taxes.assignment.pending", owner=row.owner_ref, external_ref=row.external_ref,
                source=row.source_system, action="queued on sync.pending_references; reconcile links it")
    await db.execute(
        pg_insert(PendingReference).values(
            tenant_id=row.tenant_id, organization_id=row.organization_id,
            source_system=row.source_system, module=_PENDING_MODULE, external_id=row.external_ref,
            waiting_table=_PENDING_TABLE, waiting_id=row.id, waiting_column=_PENDING_COLUMN,
        ).on_conflict_do_nothing(constraint="uq_pending_references_waiter")
    )


async def _drop_waiter(db: AsyncSession, row: TaxAssignment) -> None:
    await db.execute(delete(PendingReference).where(
        PendingReference.tenant_id == row.tenant_id,
        PendingReference.waiting_table == _PENDING_TABLE,
        PendingReference.waiting_id == row.id,
    ))


async def remove_owner_assignments(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, reason: str, actor_id: int | None = None,
) -> int:
    """Soft-delete every live assignment of an owner that is going away (all sources).

    Frozen rows are soft-deleted too — an issued document's snapshot stays in the row,
    only its liveness ends — which the frozen guard permits.
    """
    rows = await crud.list_for_owner(db, owner_type_code, owner_id)
    for row in rows:
        row.soft_delete(reason=reason, by=actor_id)
        if row.is_pending:
            await _drop_waiter(db, row)
    if rows:
        await db.flush()
    return len(rows)


async def delete_assignment(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    row = await crud.get_assignment_by_ref(db, ref)
    if row is None:
        raise NotFoundError(f"Tax assignment '{ref}' not found")
    if row.is_frozen:
        raise ConflictError("This tax assignment is frozen (issued) and cannot be removed")
    if row.source_system is not None:
        raise TaxRuleError(
            f"This assignment is maintained by {row.source_system}; change it there — the next sync brings it here",
            data={"source_system": row.source_system},
        )
    row.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(
        db, action="tax_assignment_deleted", actor_id=actor_id, subject_type=row.owner_type_code,
        subject_id=str(row.owner_id), context={"reason": reason},
    )


# ── freezing (issued documents) ────────────────────────────────────────────────

def build_snapshot(component: TaxComponent | None, exemption: Any | None) -> dict[str, Any]:
    """The tax as an issued document must keep showing it.

    A group carries its members so the split (CGST 9 + SGST 9) survives a later
    change to either. An exemption keeps its id and type only: its code and name are
    P2 (see ``exemption.py``), so the erasure job stays a single place to act.
    """
    if component is not None:
        snap: dict[str, Any] = {
            "kind": "tax",
            "tax_id": component.id,
            "tax_name": component.tax_name,
            "tax_percentage": str(component.tax_percentage if isinstance(component.tax_percentage, Decimal)
                                  else Decimal(str(component.tax_percentage))),
            "tax_type": component.tax_type,
            "tax_specific_type": component.tax_specific_type,
        }
        if component.tax_type == "tax_group":
            snap["members"] = [
                {"tax_id": m.member_tax.id, "tax_name": m.member_tax.tax_name,
                 "tax_percentage": str(m.member_tax.tax_percentage),
                 "tax_specific_type": m.member_tax.tax_specific_type}
                for m in component.members
            ]
        return snap
    return {"kind": "exemption", "tax_exemption_id": getattr(exemption, "id", None),
            "exemption_type": getattr(exemption, "exemption_type", None)}


async def freeze_owner(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, actor_id: int | None = None,
) -> int:
    """Snapshot the owner's live taxes as they are NOW; each row becomes immutable.

    For the document module to call when it issues a document. Idempotent: an already
    frozen row is left alone. An unresolved (pending) tax refuses — an issued document
    must not carry a tax nobody can name. Returns how many rows were frozen.
    """
    rows = await crud.list_for_owner(db, owner_type_code, owner_id)
    if any(row.is_pending for row in rows):
        raise TaxRuleError(f"{owner_type_code} {owner_id} has an unresolved tax; resolve it before issuing")
    components = await crud.components_by_id(db, [r.tax_component_id for r in rows if r.tax_component_id])
    now = dt.datetime.now(dt.UTC)
    frozen = 0
    for row in rows:
        if row.is_frozen:
            continue
        component = components.get(row.tax_component_id) if row.tax_component_id else None
        row.snapshot = build_snapshot(component, row.tax_exemption)
        row.frozen_at = now
        frozen += 1
    if frozen:
        await db.flush()
        await record_activity(
            db, action="tax_assignments_frozen", actor_id=actor_id, subject_type=owner_type_code,
            subject_id=str(owner_id), changes={"after": {"frozen": frozen}},
        )
    return frozen


__all__ = [
    "AssignmentSpec",
    "ResolvedTaxes",
    "TaxRuleError",
    "build_snapshot",
    "delete_assignment",
    "freeze_owner",
    "list_assignments",
    "list_policies",
    "remove_owner_assignments",
    "replace_assignments",
    "resolve_taxes",
    "select_applicable",
    "specs_from_items",
]
