"""Apply hooks for the Zoho Books chart-of-accounts adapter.

``post_upsert`` (async, runs after the page flush, row has its id) owns what the field map
cannot express:

  * **the parent** — ``parent_account_id`` names a row of THIS module, usually one in the same
    page; a page-level ``ReferenceRule`` resolves before the page is written and would defer
    every such child. Resolved here through the crosswalk; what cannot be resolved yet goes on
    ``sync.pending_references`` (``accounting.accounts.parent_id``) and the reconcile lane
    links it with a bare UPDATE — which the database triggers handle (depth, row_version,
    cycle refusal). The categories pattern, copied (docs/implementation-plan/accounts-module.md §6.1).
  * **the type's Zoho id** — ``account_type_int`` (undocumented responses) fills
    ``account_types.zoho_id`` the first time a tenant reports a type whose id we have never
    seen; set-once, a mismatch is logged and changes nothing.
  * **organization defaults** — when Zoho flags an account as THE retained-earnings / AR / AP /
    FX account (undocumented flags), the organization's slot for that purpose is filled as a
    ``source_system="zoho"`` assignment — only if the slot is empty: a person's choice is
    never overwritten.
"""

from __future__ import annotations

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_object_session

from app.modules.accounting.assignment import AccountAssignment
from app.modules.accounting.enums import CHART_OF_ACCOUNTS_MODULE
from app.modules.accounting.model import Account
from app.modules.sync.crosswalk import resolve_many
from app.modules.sync.models import PendingReference

logger = structlog.get_logger("app.accounting.zoho")

MODULE = CHART_OF_ACCOUNTS_MODULE
_TABLE = "accounting.accounts"
_COLUMN = "parent_id"
_ROOT_IDS = {None, "", "-1", -1, 0, "0"}

#: Undocumented Zoho flags → the organization-default purpose they name.
_DEFAULT_FLAGS = {
    "is_retained_earnings": "retained_earnings",
    "is_accounts_receivable": "receivable",
    "is_accounts_payable": "payable",
    "gain_or_loss_account": "fx_gain_loss",
}


async def after_account_upsert(row: Account, payload: dict) -> None:
    db = async_object_session(row)
    if db is None or row.id is None:
        return
    await _link_parent(db, row, payload)
    await _learn_type_id(db, row, payload)
    await _organization_defaults(db, row, payload)


async def _link_parent(db, row: Account, payload: dict) -> None:
    if "parent_account_id" not in payload:
        return                                   # a payload that says nothing about the parent changes nothing
    external = payload.get("parent_account_id")
    if external in _ROOT_IDS or (isinstance(external, str) and not external.strip()):
        if row.parent_id is not None:
            row.parent_id = None
        await _clear_waiter(db, row)
        return
    external = str(external).strip()
    linked = (await db.execute(resolve_many(
        tenant_id=row.tenant_id, source_system="zoho", pairs=[(MODULE, external)],
    ))).first()
    if linked is None or linked.entity_table != _TABLE or linked.entity_id is None:
        await _defer_parent(db, row, external)
        return
    if linked.entity_id == row.id:
        return
    if row.parent_id != linked.entity_id:
        row.parent_id = linked.entity_id
    await _clear_waiter(db, row)


async def _defer_parent(db, row: Account, external: str) -> None:
    logger.info("accounting.zoho.parent_pending", account_id=row.id, parent_zoho_id=external,
                action="queued on sync.pending_references; the reconcile lane links it")
    await db.execute(
        pg_insert(PendingReference).values(
            tenant_id=row.tenant_id, organization_id=row.organization_id,
            source_system="zoho", module=MODULE, external_id=external,
            waiting_table=_TABLE, waiting_id=row.id, waiting_column=_COLUMN,
        ).on_conflict_do_nothing(constraint="uq_pending_references_waiter")
    )


async def _clear_waiter(db, row: Account) -> None:
    await db.execute(delete(PendingReference).where(
        PendingReference.tenant_id == row.tenant_id,
        PendingReference.waiting_table == _TABLE,
        PendingReference.waiting_id == row.id,
        PendingReference.waiting_column == _COLUMN,
    ))


async def _learn_type_id(db, row: Account, payload: dict) -> None:
    raw = payload.get("account_type_int")
    if raw in (None, ""):
        return
    zoho_type_id = str(raw).strip()
    known = await db.scalar(text("SELECT zoho_id FROM accounting.account_types WHERE code = :code"),
                            {"code": row.account_type})
    if known is None:
        await db.execute(text("UPDATE accounting.account_types SET zoho_id = :zid, updated_at = now() "
                              "WHERE code = :code AND zoho_id IS NULL"),
                         {"zid": zoho_type_id, "code": row.account_type})
        logger.info("accounting.zoho.type_id_learned", account_type=row.account_type, zoho_id=zoho_type_id)
    elif known != zoho_type_id:
        logger.warning("accounting.type_id_mismatch", account_type=row.account_type, seeded=known,
                       reported=zoho_type_id)


async def _organization_defaults(db, row: Account, payload: dict) -> None:
    for flag, purpose in _DEFAULT_FLAGS.items():
        if payload.get(flag) not in (True, "true", "True", 1):
            continue
        taken = await db.scalar(
            select(AccountAssignment.id).where(
                AccountAssignment.organization_id == row.organization_id,
                AccountAssignment.owner_type_code == "organization",
                AccountAssignment.owner_id == row.organization_id,
                AccountAssignment.purpose_code == purpose,
                AccountAssignment.currency_id.is_(None),
            ).limit(1)
        )
        if taken is not None:
            continue
        fits = await db.scalar(text(
            "SELECT t.account_group = ANY(p.allowed_groups) AND (p.allowed_types IS NULL OR t.code = ANY(p.allowed_types))"
            "  FROM accounting.account_purposes p, accounting.account_types t"
            " WHERE p.code = :purpose AND t.code = :type"), {"purpose": purpose, "type": row.account_type})
        if not fits:
            # The integrity trigger would refuse it at COMMIT and fail the whole record; log and move on.
            logger.warning("accounting.zoho.organization_default_skipped", purpose=purpose, account_id=row.id,
                           account_type=row.account_type, reason="account type does not fit the purpose")
            continue
        db.add(AccountAssignment(
            tenant_id=row.tenant_id, organization_id=row.organization_id, owner_type_code="organization",
            owner_id=row.organization_id, purpose_code=purpose, account_id=row.id, source_system="zoho",
            external_ref=row.zoho_id,
        ))
        await db.flush()
        logger.info("accounting.zoho.organization_default", purpose=purpose, account_id=row.id)


__all__ = ["MODULE", "after_account_upsert"]
