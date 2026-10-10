"""Data access for the chart of accounts and account assignments (crud layer — no business logic).

Loader strategy, stated once: every relationship is ``lazy="raise"``. Lists select the Slim
column set with ``load_only`` (``AccountSlimOut``); the detail read joins the type and the
parent explicitly. Nothing here can trigger a lazy load.
"""

from __future__ import annotations

import uuid as uuid_lib
from collections.abc import Iterable

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only

from app.modules.accounting.assignment import AccountAssignment, AccountPurpose, AccountPurposePolicy
from app.modules.accounting.enums import AccountUsage
from app.modules.accounting.model import Account, AccountType

_SLIM = (
    Account.id, Account.uuid, Account.account_code, Account.account_name, Account.display_name,
    Account.account_type, Account.parent_id, Account.depth, Account.status, Account.normal_balance_is_debit,
    Account.zoho_id,
)

_USAGE_FLAG = {
    AccountUsage.SALES: AccountType.is_sales_eligible,
    AccountUsage.PURCHASE: AccountType.is_purchase_eligible,
    AccountUsage.INVENTORY: AccountType.is_inventory_eligible,
}


# ── types / purposes / policies ───────────────────────────────────────────────

async def list_types(db: AsyncSession, *, enabled_only: bool = False) -> list[AccountType]:
    stmt = select(AccountType).order_by(AccountType.sort_order, AccountType.code)
    if enabled_only:
        stmt = stmt.where(AccountType.is_enabled.is_(True))
    return list((await db.scalars(stmt)).all())


async def get_type(db: AsyncSession, code: str) -> AccountType | None:
    return await db.scalar(select(AccountType).where(AccountType.code == code).limit(1))


async def list_purposes(db: AsyncSession) -> list[AccountPurpose]:
    return list((await db.scalars(select(AccountPurpose).order_by(AccountPurpose.sort_order))).all())


async def purposes_by_code(db: AsyncSession, codes: Iterable[str]) -> dict[str, AccountPurpose]:
    wanted = set(codes)
    if not wanted:
        return {}
    rows = await db.scalars(select(AccountPurpose).where(AccountPurpose.code.in_(wanted)))
    return {row.code: row for row in rows.all()}


async def list_policies(db: AsyncSession, entity_type_code: str | None = None) -> list[AccountPurposePolicy]:
    stmt = select(AccountPurposePolicy).order_by(AccountPurposePolicy.entity_type_code,
                                                 AccountPurposePolicy.purpose_code)
    if entity_type_code:
        stmt = stmt.where(AccountPurposePolicy.entity_type_code == entity_type_code)
    return list((await db.scalars(stmt)).all())


async def policies_for(db: AsyncSession, entity_type_code: str, purposes: Iterable[str]) -> dict[str, AccountPurposePolicy]:
    wanted = set(purposes)
    if not wanted:
        return {}
    rows = await db.scalars(select(AccountPurposePolicy).where(
        AccountPurposePolicy.entity_type_code == entity_type_code, AccountPurposePolicy.purpose_code.in_(wanted)))
    return {row.purpose_code: row for row in rows.all()}


# ── accounts ──────────────────────────────────────────────────────────────────

async def list_accounts_slim(
    db: AsyncSession, *, group: str | None = None, account_type: str | None = None,
    usage: AccountUsage | None = None, status: str | None = None, parent_id: int | None = None,
    roots_only: bool = False, q: str | None = None, include_deleted: bool = False,
    limit: int | None = None, offset: int = 0,
) -> list[Account]:
    stmt = select(Account).options(load_only(*_SLIM)).order_by(Account.account_name, Account.id)
    if group or usage:
        stmt = stmt.join(AccountType, AccountType.code == Account.account_type)
        if group:
            stmt = stmt.where(AccountType.account_group == group)
        if usage:
            stmt = stmt.where(_USAGE_FLAG[usage].is_(True))
    if account_type:
        stmt = stmt.where(Account.account_type == account_type)
    if status:
        stmt = stmt.where(Account.status == status)
    if parent_id is not None:
        stmt = stmt.where(Account.parent_id == parent_id)
    if roots_only:
        stmt = stmt.where(Account.parent_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Account.account_name.ilike(like), Account.account_code.ilike(like)))
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


async def get_account(db: AsyncSession, ref: str | int, *, include_deleted: bool = False) -> Account | None:
    if isinstance(ref, int) or str(ref).isdigit():
        condition = Account.id == int(ref)
    else:
        try:
            condition = Account.uuid == uuid_lib.UUID(str(ref))
        except ValueError:
            return None
    stmt = select(Account).where(condition).options(joinedload(Account.type_ref), joinedload(Account.parent)).limit(1)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return await db.scalar(stmt)


async def accounts_by_id(db: AsyncSession, ids: Iterable[int]) -> dict[int, Account]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await db.scalars(select(Account).where(Account.id.in_(wanted)).options(joinedload(Account.type_ref)))
    return {row.id: row for row in rows.unique().all()}


async def live_children_count(db: AsyncSession, account_id: int) -> int:
    return int(await db.scalar(select(func.count()).select_from(Account).where(Account.parent_id == account_id)) or 0)


async def with_children(db: AsyncSession, ids: Iterable[int]) -> set[int]:
    wanted = set(ids)
    if not wanted:
        return set()
    rows = await db.scalars(select(Account.parent_id).where(Account.parent_id.in_(wanted)).distinct())
    return set(rows.all())


async def assignment_count(db: AsyncSession, account_id: int) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(AccountAssignment).where(AccountAssignment.account_id == account_id)
    ) or 0)


# ── assignments ───────────────────────────────────────────────────────────────

async def list_for_owner(db: AsyncSession, owner_type_code: str, owner_id: int) -> list[AccountAssignment]:
    stmt = (
        select(AccountAssignment)
        .where(AccountAssignment.owner_type_code == owner_type_code, AccountAssignment.owner_id == owner_id)
        .options(joinedload(AccountAssignment.account).load_only(*_SLIM))
        .order_by(AccountAssignment.purpose_code, AccountAssignment.id)
    )
    return list((await db.scalars(stmt)).unique().all())


async def list_for_owners(db: AsyncSession, owners: Iterable[tuple[str, int]]) -> list[AccountAssignment]:
    wanted = sorted(set(owners))
    if not wanted:
        return []
    stmt = (
        select(AccountAssignment)
        .where(tuple_(AccountAssignment.owner_type_code, AccountAssignment.owner_id).in_(wanted))
        .options(joinedload(AccountAssignment.account).load_only(*_SLIM))
    )
    return list((await db.scalars(stmt)).unique().all())


__all__ = [
    "accounts_by_id",
    "assignment_count",
    "get_account",
    "get_type",
    "list_accounts_slim",
    "list_for_owner",
    "list_for_owners",
    "list_policies",
    "list_purposes",
    "list_types",
    "live_children_count",
    "policies_for",
    "purposes_by_code",
    "with_children",
]
