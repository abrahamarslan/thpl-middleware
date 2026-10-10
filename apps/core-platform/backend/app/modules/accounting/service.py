"""Chart of accounts — business logic.

| Rule | Pre-flight (clean 4xx) | Database (authoritative) |
|---|---|---|
| organization required | ``scope.require_organization_id`` | ``OrgEntityMixin`` NOT NULL + composite FK |
| a Zoho-mastered chart takes no local accounts (until outbound) | ``_refuse_if_zoho_mastered`` | — |
| Zoho-owned fields read-only on a linked account | ``_guard_zoho_owned`` | — |
| the type exists and is enabled | ``_type`` | FK ``fk_accounts_account_type`` |
| the parent is in the same organization | ``_parent`` | FK ``fk_accounts_parent_scope`` |
| no cycles | ``_parent`` | ``accounting.derive_account_fields`` |
| the parent's type allows sub-accounts; parent and child in one group | ``check_type_rules`` | — (Zoho is the arbiter of ITS chart; ``find_chart_violations`` reports) |
| code unique per organization | — | ``uq_accounts_code`` |
| a system account is not deleted or re-typed | ``update`` / ``delete`` | — |
| no delete with children or assignments | ``delete`` (409) | ``accounting.guard_account_delete`` |
| depth, normal side | — | derived by trigger |

Zoho HTTP never happens here. ``to_zoho_payload`` builds the outbound body the command
outbox will send (Phase 6).
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.database import scope
from app.modules.accounting import crud
from app.modules.accounting.errors import (
    AccountInUseError,
    AccountRuleError,
    ZohoMasteredChartError,
    ZohoOwnedFieldError,
)
from app.modules.accounting.model import Account, AccountType
from app.modules.accounting.schema import AccountCreate, AccountUpdate
from app.modules.activity.recorder import record_activity
from app.modules.organizations.model import Organization
from app.modules.sync.translation import WriteIntent

logger = structlog.get_logger("app.accounting.service")


async def _type(db: AsyncSession, code: str) -> AccountType:
    account_type = await crud.get_type(db, code)
    if account_type is None:
        raise AccountRuleError(f"Unknown account type '{code}'",
                               data={"hint": "GET /api/accounting/account-types lists them"})
    if not account_type.is_enabled:
        raise AccountRuleError(f"Account type '{code}' is retired")
    return account_type


async def _parent(db: AsyncSession, parent_id: int, organization_id: int, *, child_id: int | None = None) -> Account:
    parent = await crud.get_account(db, parent_id)
    if parent is None or parent.organization_id != organization_id:
        raise AccountRuleError(f"Parent account {parent_id} does not exist in this organization")
    if child_id is not None:
        # Walk up from the proposed parent: meeting the child means the move makes a cycle.
        ancestor: Account | None = parent
        for _ in range(64):
            if ancestor is None:
                break
            if ancestor.id == child_id:
                raise AccountRuleError("An account cannot be moved under its own descendant")
            ancestor = await crud.get_account(db, ancestor.parent_id) if ancestor.parent_id else None
    return parent


def check_type_rules(child_type: AccountType, parent: Account | None) -> None:
    """Zoho's sub-account rules, applied to LOCAL writes."""
    if parent is None:
        return
    parent_type: AccountType = parent.type_ref
    if parent_type.is_sub_account_allowed is False:
        raise AccountRuleError(f"Accounts of type '{parent_type.code}' cannot have sub-accounts",
                               data={"rule": "sub_account_not_allowed"})
    if parent_type.account_group != child_type.account_group:
        raise AccountRuleError(
            f"A sub-account must be in its parent's group ({parent_type.account_group}), "
            f"not {child_type.account_group}", data={"rule": "parent_group_mismatch"})


async def _refuse_if_zoho_mastered(db: AsyncSession, organization_id: int) -> None:
    organization = await db.get(Organization, organization_id)
    if organization is not None and organization.zoho_id is not None:
        raise ZohoMasteredChartError(
            "This organization's chart of accounts is mastered by Zoho Books — create the account in Zoho; "
            "the next sync brings it here", data={"zoho_organization_id": organization.zoho_id})


def _guard_zoho_owned(account: Account, changes: dict[str, Any]) -> None:
    if not account.is_zoho_linked:
        return
    from app.modules.accounting.zoho.spec import ZOHO_OWNED_ACCOUNT_FIELDS   # the adapter imports this package

    blocked = sorted(set(changes) & (ZOHO_OWNED_ACCOUNT_FIELDS | {"status"}))
    if blocked:
        raise ZohoOwnedFieldError(
            f"{', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} owned by Zoho for this account "
            f"(zoho_id {account.zoho_id}); change it in Zoho — the next sync brings it here",
            data={"fields": blocked})


async def create_account(db: AsyncSession, body: AccountCreate, *, actor_id: int | None = None) -> Account:
    organization_id = await scope.require_organization_id(db)
    await _refuse_if_zoho_mastered(db, organization_id)
    account_type = await _type(db, body.account_type)
    parent = await _parent(db, body.parent_id, organization_id) if body.parent_id else None
    check_type_rules(account_type, parent)
    account = Account(organization_id=organization_id, **body.model_dump(exclude_none=True))
    db.add(account)
    await db.flush()
    await record_activity(db, action="account_created", actor_id=actor_id, subject_type="account",
                          subject_id=str(account.id), changes={"after": body.model_dump(mode="json")})
    return await get_account(db, account.id)


async def get_account(db: AsyncSession, ref: str | int) -> Account:
    account = await crud.get_account(db, ref)
    if account is None:
        raise NotFoundError(f"Account '{ref}' not found")
    return account


async def update_account(db: AsyncSession, ref: str, body: AccountUpdate, *, actor_id: int | None = None) -> Account:
    account = await get_account(db, ref)
    changes = body.model_dump(exclude_unset=True)
    _guard_zoho_owned(account, changes)
    if "account_type" in changes and changes["account_type"] != account.account_type and account.is_system_account:
        raise AccountRuleError("A system account cannot change type")
    new_type = await _type(db, changes.get("account_type") or account.account_type)
    new_parent_id = changes.get("parent_id", account.parent_id)
    parent = (await _parent(db, new_parent_id, account.organization_id, child_id=account.id)
              if new_parent_id else None)
    if "account_type" in changes or "parent_id" in changes:
        check_type_rules(new_type, parent)
    before = {key: getattr(account, key) for key in changes}
    for key, value in changes.items():
        setattr(account, key, value)
    await db.flush()
    await record_activity(db, action="account_updated", actor_id=actor_id, subject_type="account",
                          subject_id=str(account.id), changes={"before": before, "after": changes})
    account_id = account.id
    db.expire(account)                      # triggers derived depth / normal side; read them fresh
    return await get_account(db, account_id)


async def set_status(db: AsyncSession, ref: str, status: str, *, actor_id: int | None = None) -> Account:
    account = await get_account(db, ref)
    _guard_zoho_owned(account, {"status": status})
    if account.status != status:
        account.status = status
        await db.flush()
        await record_activity(db, action=f"account_{status}", actor_id=actor_id, subject_type="account",
                              subject_id=str(account.id))
    return await get_account(db, account.id)


async def delete_account(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None = None) -> None:
    account = await get_account(db, ref)
    if account.is_zoho_linked:
        raise ZohoOwnedFieldError("This account is mastered by Zoho Books — delete it in Zoho")
    if account.is_system_account:
        raise AccountRuleError("A system account cannot be deleted")
    children = await crud.live_children_count(db, account.id)
    used = await crud.assignment_count(db, account.id)
    if children or used:
        raise AccountInUseError(f"Account is in use: {children} sub-account(s), {used} assignment(s)",
                                data={"children": children, "assignments": used})
    account.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(db, action="account_deleted", actor_id=actor_id, subject_type="account",
                          subject_id=str(account.id), changes={"reason": reason})


async def describe(db: AsyncSession, account: Account) -> dict[str, Any]:
    """The Fat view's computed fields."""
    return {
        "account_group": account.type_ref.account_group if account.type_ref else None,
        "parent_display_name": account.parent.display_name if account.parent else None,
        "has_children": bool(await crud.with_children(db, [account.id])),
        "assignment_count": await crud.assignment_count(db, account.id),
    }


def build_tree(rows: list[Account]) -> list[dict[str, Any]]:
    """Nest a flat list (one query) into roots with children; orphans (parent filtered out) become roots."""
    from app.modules.accounting.schema import AccountSlimOut

    nodes = {row.id: {**AccountSlimOut.model_validate(row).model_dump(), "children": []} for row in rows}
    roots: list[dict[str, Any]] = []
    for row in rows:
        node = nodes[row.id]
        if row.parent_id is not None and row.parent_id in nodes:
            nodes[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


async def find_chart_violations(db: AsyncSession, organization_id: int) -> list[dict[str, Any]]:
    """Accounts whose parent breaks Zoho's own sub-account rules — REPORTED, never refused (§5.3)."""
    rows = (await db.execute(text("""
        SELECT c.id, c.display_name, c.account_type, p.id, p.account_type,
               CASE WHEN pt.is_sub_account_allowed IS FALSE THEN 'sub_account_not_allowed'
                    ELSE 'parent_group_mismatch' END
          FROM accounting.accounts c
          JOIN accounting.accounts p ON p.id = c.parent_id
          JOIN accounting.account_types ct ON ct.code = c.account_type
          JOIN accounting.account_types pt ON pt.code = p.account_type
         WHERE c.organization_id = :org AND c.deleted_at IS NULL
           AND (pt.is_sub_account_allowed IS FALSE OR pt.account_group <> ct.account_group)
         ORDER BY c.id
    """), {"org": organization_id})).all()
    return [{"account_id": r[0], "display_name": r[1], "account_type": r[2], "parent_id": r[3],
             "parent_type": r[4], "reason": r[5]} for r in rows]


def to_zoho_payload(account: Account, *, intent: WriteIntent = WriteIntent.UPDATE) -> dict[str, Any]:
    """The outbound body for ``POST/PUT /chartofaccounts`` (Phase 6 outbox seam)."""
    from app.modules.accounting.zoho.spec import CHART_OF_ACCOUNTS_TRANSLATOR

    return CHART_OF_ACCOUNTS_TRANSLATOR.encode(account, intent=intent)


__all__ = [
    "build_tree",
    "check_type_rules",
    "create_account",
    "delete_account",
    "describe",
    "find_chart_violations",
    "get_account",
    "set_status",
    "to_zoho_payload",
    "update_account",
]
