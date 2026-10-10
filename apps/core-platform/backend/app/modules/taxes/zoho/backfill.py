"""Replay the stored Zoho tax documents through the tax → ledger-account hook — zero API calls.

A normal sync never revisits a tax that has not changed (the apply gate skips it), so taxes
synced BEFORE account assignments existed would never get their ``output_tax`` /
``input_tax`` / ``tds_payable`` links. Every crosswalk row keeps the full detail document it
last applied (``sync.sync_records.raw``) — ``tax_account_id`` and friends included — so this
reads it and runs it through the very same ``hooks.link_tax_accounts`` the sync uses. The
result is identical to what the next real sync would write.

Idempotent (the writer is a diff), safe to re-run; a tax whose stored document is a thin list
row (no account keys) is skipped.

    docker exec backend python -m app.modules.taxes.zoho.backfill

Run it after ``chart_of_accounts`` has synced (an account that is not there yet becomes a
*pending* assignment that the reconcile lane links later — also fine).
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass

import structlog
from sqlalchemy import select

from app.database.db import async_session_factory
from app.modules.sync.models import SyncRecord
from app.modules.taxes.component import TaxComponent
from app.modules.taxes.zoho import hooks
from app.modules.zoho.control.tenancy import zoho_scope

logger = structlog.get_logger("app.taxes.zoho.backfill")


@dataclass(slots=True)
class BackfillReport:
    scanned: int = 0
    replayed: int = 0
    skipped_thin: int = 0


async def backfill_tax_accounts(db) -> BackfillReport:
    """Replay every synced tax's stored document; the caller owns the scope and the commit."""
    report = BackfillReport()
    records = (await db.execute(
        select(SyncRecord.entity_id, SyncRecord.raw).where(
            SyncRecord.source_system == "zoho", SyncRecord.module.in_(("taxes", "tax_groups")),
            SyncRecord.entity_id.is_not(None), SyncRecord.remote_deleted_at.is_(None),
        )
    )).all()
    components = {c.id: c for c in (await db.scalars(
        select(TaxComponent).where(TaxComponent.id.in_([entity_id for entity_id, _ in records]))
    )).all()}
    for entity_id, raw in records:
        report.scanned += 1
        component = components.get(entity_id)
        if component is None:
            continue
        if not isinstance(raw, dict) or not any(key in raw for key in hooks.TAX_ACCOUNT_PURPOSES):
            report.skipped_thin += 1
            continue
        await hooks.link_tax_accounts(component, raw)
        report.replayed += 1
    logger.info("taxes.zoho.backfill_tax_accounts", scanned=report.scanned, replayed=report.replayed,
                skipped_thin=report.skipped_thin)
    return report


async def _main() -> int:
    # Map every model, as the API and the worker do — by NAME: a static import of the router would make
    # taxes import every feature module (.importlinter: taxes is independent of the other masters).
    importlib.import_module("app.router")

    from app.database.db import engine
    from app.database.redis import redis_client

    try:
        async with async_session_factory() as db:
            async with zoho_scope(db):
                report = await backfill_tax_accounts(db)
                await db.commit()
        print(f"taxes scanned={report.scanned} replayed={report.replayed} skipped_thin={report.skipped_thin}")
        return 0
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
