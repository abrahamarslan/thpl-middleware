"""Replay the stored Zoho documents through the tax-preference hook — zero API calls.

A normal sync never revisits a category that has not changed (the apply gate skips
it), so categories synced BEFORE tax assignments existed would never get theirs. But
every crosswalk row keeps the full detail document it last applied
(``sync.sync_records.raw``), ``category_tax_preferences`` included. This reads that
and runs it through the very same ``hooks._sync_tax_preferences`` the sync uses, so
the result is identical to what the next real sync would write.

Idempotent (the writer is a diff), safe to re-run, and a no-op for a category whose
stored document is a thin list row (no ``category_tax_preferences`` key).

    docker exec backend python -m app.modules.categories.zoho.backfill

Run it after the ``taxes`` module has synced (a tax that is not there yet becomes a
*pending* assignment that the reconcile lane links later — also fine).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy import select

from app.database.db import async_session_factory
from app.modules.categories.model import Category
from app.modules.categories.zoho import hooks
from app.modules.sync.models import SyncRecord
from app.modules.zoho.control.tenancy import zoho_scope

logger = structlog.get_logger("app.categories.zoho.backfill")


@dataclass(slots=True)
class BackfillReport:
    scanned: int = 0
    replayed: int = 0
    skipped_thin: int = 0


async def backfill_tax_preferences(db) -> BackfillReport:
    """Replay every synced category's stored document; the caller owns the scope and the commit."""
    report = BackfillReport()
    records = (await db.execute(
        select(SyncRecord.entity_id, SyncRecord.raw).where(
            SyncRecord.source_system == "zoho", SyncRecord.module == "categories",
            SyncRecord.entity_id.is_not(None), SyncRecord.remote_deleted_at.is_(None),
        )
    )).all()
    categories = {c.id: c for c in (await db.scalars(
        select(Category).where(Category.id.in_([entity_id for entity_id, _ in records]))
    )).all()}
    for entity_id, raw in records:
        report.scanned += 1
        category = categories.get(entity_id)
        if category is None:
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("category_tax_preferences"), list):
            report.skipped_thin += 1
            continue
        await hooks._sync_tax_preferences(db, category, raw)          # noqa: SLF001 — the one shared writer
        report.replayed += 1
    return report


async def _main() -> int:
    import app.router  # noqa: F401 — map every model, as the API and the worker do

    from app.database.db import engine
    from app.database.redis import redis_client

    try:
        async with async_session_factory() as db:
            async with zoho_scope(db):
                report = await backfill_tax_preferences(db)
                await db.commit()
        print(f"categories scanned={report.scanned} replayed={report.replayed} skipped_thin={report.skipped_thin}")
        return 0
    finally:
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
