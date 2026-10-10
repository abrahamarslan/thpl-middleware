"""Account assignments — what accounts an entity uses, for any entity.

| Rule | Pre-flight (clean 422/409) | Database (authoritative) |
|---|---|---|
| class registered AND opted in to the purpose | ``_policies`` | FK ``→ account_purpose_policies`` |
| owner exists | ``_owner`` | deferred ``assert_entity_exists`` |
| owner in scope (same organization, or tenant-wide) | ``_organization`` | deferred ``core.assert_owner_scope`` |
| the account is the organization's and live | ``_validate`` | composite FK ``fk_account_assignments_account`` |
| a LOCAL row's account is active and its group / type fits the purpose | ``_validate`` | deferred integrity trigger (local rows) |
| a currency only on a per-currency purpose | ``_validate`` | deferred integrity trigger |
| one account per slot | ``_validate`` | ``uq_account_assignments_slot`` |
| a source's rows are not edited locally (and vice versa) | ``put_assignments`` (409) | — |

One writer: :func:`put_assignments`. The API, the Zoho hooks (taxes today; items and contacts
next) all call it — directly or through :func:`sync_source_assignments` — so a person and a
sync are held to the same rules.

"Which account applies?" is NOT answered here: that is the resolution engine
(``app.modules.resolution``, facet ``account``) — it walks an owner chain and falls back to the
organization.

**A source's rows are trusted, not judged.** Zoho masters its own chart and its own tax ↔
account links; a Zoho tax that posts to an account of an unexpected group is Zoho's data, and
refusing it would make the replica wrong, not Zoho right (the chart-of-accounts doctrine,
docs/implementation-plan/accounts-module.md §2.3 #6). Group / type / activity rules apply to
LOCAL rows; a source row that breaks one is written and LOGGED
(``accounting.assignment.source_misfit``). The database trigger draws the same line, which
also keeps the reconcile lane — one transaction for a whole batch of waiters — from failing
on one odd link.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.database import scope
from app.modules.accounting import crud
from app.modules.accounting.assignment import AccountAssignment, AccountPurposePolicy
from app.modules.accounting.errors import AccountRuleError
from app.modules.accounting.enums import CHART_OF_ACCOUNTS_MODULE as ACCOUNTS_MODULE
from app.modules.activity.recorder import record_activity
from app.modules.entities.crud import OwnerInfo, owner_info
from app.modules.sync.crosswalk import resolve_many
from app.modules.sync.models import PendingReference

logger = structlog.get_logger("app.accounting.assignments")

_PENDING_TABLE = "accounting.account_assignments"
_PENDING_COLUMN = "account_id"
_ACCOUNTS_TABLE = "accounting.accounts"


@dataclass(frozen=True, slots=True)
class AccountSpec:
    """One desired assignment: a purpose (and currency) → an account, or a source's pending account id."""

    purpose: str
    account_id: int | None = None
    currency_id: int | None = None
    external_ref: str | None = None

    @property
    def slot(self) -> tuple[str, int | None]:
        return self.purpose, self.currency_id


# ── reads ─────────────────────────────────────────────────────────────────────

async def list_assignments(db: AsyncSession, owner_type_code: str, owner_id: int) -> list[AccountAssignment]:
    return await crud.list_for_owner(db, owner_type_code, owner_id)


# ── the one writer ─────────────────────────────────────────────────────────────

async def _owner(db: AsyncSession, owner_type_code: str, owner_id: int) -> OwnerInfo:
    info = await owner_info(db, owner_type_code, owner_id)
    if not info.exists:
        raise NotFoundError(f"{owner_type_code} {owner_id} not found")
    return info


async def _organization(db: AsyncSession, info: OwnerInfo, given: int | None) -> int:
    """The organization whose chart the assignments use.

    An org-scoped owner fixes it (a different ``given`` is refused). A tenant-wide owner (a
    shared tax) uses the one given, else the request's.
    """
    if info.organization_id is not None:
        if given is not None and given != info.organization_id:
            raise AccountRuleError("This owner belongs to another organization than the one given")
        return info.organization_id
    if given is not None:
        return given
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise AccountRuleError(exc.msg, data=exc.data) from exc


async def _policies(db: AsyncSession, owner_type_code: str, purposes: set[str]) -> dict[str, AccountPurposePolicy]:
    found = await crud.policies_for(db, owner_type_code, purposes)
    missing = sorted(purposes - set(found))
    if missing:
        raise AccountRuleError(f"'{owner_type_code}' cannot carry account purpose(s) {missing}",
                               data={"hint": "GET /api/accounting/purpose-policies lists what each class may carry"})
    disabled = sorted(p for p, policy in found.items() if not policy.is_enabled)
    if disabled:
        raise AccountRuleError(f"Account purpose(s) {disabled} are disabled for '{owner_type_code}'")
    return found


async def _validate(
    db: AsyncSession, specs: Sequence[AccountSpec], organization_id: int, *, source_system: str | None,
) -> None:
    slots = [s.slot for s in specs]
    if len(slots) != len(set(slots)):
        raise AccountRuleError("Each purpose (and currency) may be assigned once")
    purposes = await crud.purposes_by_code(db, {s.purpose for s in specs})
    accounts = await crud.accounts_by_id(db, [s.account_id for s in specs if s.account_id])
    for spec in specs:
        purpose = purposes.get(spec.purpose)
        if purpose is None or not purpose.is_enabled:
            raise AccountRuleError(f"Unknown or disabled account purpose '{spec.purpose}'")
        if spec.currency_id is not None and not purpose.per_currency:
            raise AccountRuleError(f"'{spec.purpose}' is not per-currency; leave the currency empty")
        if spec.account_id is None:
            continue
        account = accounts.get(spec.account_id)
        if account is None or account.organization_id != organization_id:
            raise AccountRuleError(f"Account {spec.account_id} does not exist in organization {organization_id}")
        if source_system is not None:
            misfit = _misfit(purpose, account)
            if misfit:
                logger.warning("accounting.assignment.source_misfit", source=source_system, purpose=spec.purpose,
                               account_id=account.id, account_type=account.account_type, problem=misfit)
            continue
        if not account.is_active:
            raise AccountRuleError(f"Account '{account.display_name}' is inactive")
        group = account.type_ref.account_group
        if group not in purpose.allowed_groups:
            raise AccountRuleError(
                f"'{spec.purpose}' needs a {'/'.join(purpose.allowed_groups)} account; "
                f"'{account.display_name}' is {group}", data={"rule": "account_group_not_allowed"})
        if purpose.allowed_types and account.account_type not in purpose.allowed_types:
            raise AccountRuleError(
                f"'{spec.purpose}' needs an account of type {'/'.join(purpose.allowed_types)}; "
                f"'{account.display_name}' is {account.account_type}", data={"rule": "account_type_not_allowed"})


def _misfit(purpose, account) -> str | None:
    if account.type_ref.account_group not in purpose.allowed_groups:
        return f"group {account.type_ref.account_group} not in {purpose.allowed_groups}"
    if purpose.allowed_types and account.account_type not in purpose.allowed_types:
        return f"type {account.account_type} not in {purpose.allowed_types}"
    return None


async def put_assignments(
    db: AsyncSession, owner_type_code: str, owner_id: int, specs: Sequence[AccountSpec], *,
    source_system: str | None = None, organization_id: int | None = None, actor_id: int | None = None,
) -> list[AccountAssignment]:
    """Make ``specs`` the complete set of accounts this ``source_system`` maintains for the owner.

    Diff-based and idempotent: unchanged slots are kept, changed ones re-pointed, dropped ones
    soft-deleted, new ones inserted. Only rows of the SAME ``source_system`` (``None`` =
    local) are touched — a sync never removes what a person set, and a person cannot take a
    slot a source maintains (409).
    """
    info = await _owner(db, owner_type_code, owner_id)
    org_id = await _organization(db, info, organization_id)
    await _policies(db, owner_type_code, {s.purpose for s in specs})
    await _validate(db, specs, org_id, source_system=source_system)

    existing = [row for row in await crud.list_for_owner(db, owner_type_code, owner_id)
                if row.organization_id == org_id]
    foreign = {(row.purpose_code, row.currency_id): row.source_system
               for row in existing if row.source_system != source_system}
    for spec in specs:
        if spec.slot in foreign:
            holder = foreign[spec.slot]
            raise ConflictError(
                f"'{spec.purpose}' of {owner_type_code} {owner_id} is "
                f"{'maintained by ' + holder if holder else 'set locally'}; it cannot also be set "
                f"{'by ' + source_system if source_system else 'locally'}",
                data={"purpose": spec.purpose, "currency_id": spec.currency_id})
    mine = {(row.purpose_code, row.currency_id): row for row in existing if row.source_system == source_system}
    wanted = {spec.slot: spec for spec in specs}

    for slot, row in mine.items():
        if slot not in wanted:
            row.soft_delete(reason=f"replaced ({source_system or 'local'})", by=actor_id)
            if row.is_pending:
                await _drop_waiter(db, row)
    await db.flush()                      # free the slot before a replacement is inserted

    touched: list[AccountAssignment] = []
    for slot, spec in wanted.items():
        row = mine.get(slot)
        if row is not None:
            if row.account_id != spec.account_id or row.external_ref != spec.external_ref:
                was_pending = row.is_pending
                row.account_id, row.external_ref = spec.account_id, spec.external_ref
                touched.append(row)
                if was_pending and not row.is_pending:
                    await _drop_waiter(db, row)
            continue
        row = AccountAssignment(
            owner_type_code=owner_type_code, owner_id=owner_id, organization_id=org_id,
            purpose_code=spec.purpose, account_id=spec.account_id, currency_id=spec.currency_id,
            external_ref=spec.external_ref, source_system=source_system,
        )
        db.add(row)
        touched.append(row)
    await db.flush()
    for row in touched:
        if row.is_pending:
            await _queue_waiter(db, row)

    if touched or len(mine) != len(wanted):
        await record_activity(
            db, action="account_assignments_replaced", actor_id=actor_id, subject_type=owner_type_code,
            subject_id=str(owner_id),
            changes={"after": {"source": source_system or "local", "organization_id": org_id,
                               "accounts": [{"purpose": s.purpose, "account": s.account_id or s.external_ref,
                                             "currency_id": s.currency_id} for s in specs]}},
        )
    return [row for row in await crud.list_for_owner(db, owner_type_code, owner_id) if row.organization_id == org_id]


async def sync_source_assignments(
    db: AsyncSession, owner: tuple[str, int], *, source_system: str, refs: Mapping[str, str | None],
    organization_id: int | None = None, tenant_id: int,
) -> list[AccountAssignment]:
    """A source names its accounts by ITS ids — resolve them through the crosswalk and write.

    ``refs`` is ``{purpose: source account id}``; a purpose whose id is empty is not carried
    (and a previously synced one is removed). An id we have not synced becomes a *pending*
    row on ``sync.pending_references`` — the reconcile lane links it when the chart arrives.
    ONE crosswalk query for every ref.
    """
    wanted = {purpose: str(ref).strip() for purpose, ref in refs.items() if ref not in (None, "", "0", 0)}
    resolved: dict[str, int] = {}
    if wanted:
        rows = await db.execute(resolve_many(
            tenant_id=tenant_id, source_system=source_system,
            pairs=[(ACCOUNTS_MODULE, ref) for ref in wanted.values()],
        ))
        for _module, external_id, entity_table, entity_id, _state in rows:
            if entity_id is not None and entity_table == _ACCOUNTS_TABLE:
                resolved[external_id] = entity_id
    # The source's id is kept on the row ALWAYS — resolved or pending (redesign §4.1 step 3): it says which
    # Zoho account the link came from, and lets a reconciler repair a link without re-reading Zoho.
    specs = [AccountSpec(purpose=purpose, account_id=resolved.get(ref), external_ref=ref)
             for purpose, ref in wanted.items()]
    return await put_assignments(db, owner[0], owner[1], specs, source_system=source_system,
                                 organization_id=organization_id)


async def _queue_waiter(db: AsyncSession, row: AccountAssignment) -> None:
    logger.info("accounting.assignment.pending", owner=row.owner_ref, purpose=row.purpose_code,
                external_ref=row.external_ref, source=row.source_system,
                action="queued on sync.pending_references; the reconcile lane links it")
    await db.execute(
        pg_insert(PendingReference).values(
            tenant_id=row.tenant_id, organization_id=row.organization_id,
            source_system=row.source_system, module=ACCOUNTS_MODULE, external_id=row.external_ref,
            waiting_table=_PENDING_TABLE, waiting_id=row.id, waiting_column=_PENDING_COLUMN,
        ).on_conflict_do_nothing(constraint="uq_pending_references_waiter")
    )


async def _drop_waiter(db: AsyncSession, row: AccountAssignment) -> None:
    await db.execute(delete(PendingReference).where(
        PendingReference.tenant_id == row.tenant_id,
        PendingReference.waiting_table == _PENDING_TABLE,
        PendingReference.waiting_id == row.id,
    ))


async def specs_from_items(db: AsyncSession, items: Sequence) -> list[AccountSpec]:
    """API items (``account`` = id or uuid) → the write model."""
    specs: list[AccountSpec] = []
    for item in items:
        account = await crud.get_account(db, item.account)
        if account is None:
            raise AccountRuleError(f"Account '{item.account}' not found")
        specs.append(AccountSpec(purpose=item.purpose, account_id=account.id, currency_id=item.currency_id))
    return specs


async def remove_owner_assignments(
    db: AsyncSession, owner_type_code: str, owner_id: int, *, reason: str, actor_id: int | None = None,
) -> int:
    """Soft-delete every live assignment of an owner that is going away (all sources)."""
    rows = await crud.list_for_owner(db, owner_type_code, owner_id)
    for row in rows:
        row.soft_delete(reason=reason, by=actor_id)
        if row.is_pending:
            await _drop_waiter(db, row)
    if rows:
        await db.flush()
    return len(rows)


__all__ = [
    "AccountSpec",
    "list_assignments",
    "put_assignments",
    "remove_owner_assignments",
    "specs_from_items",
    "sync_source_assignments",
]
