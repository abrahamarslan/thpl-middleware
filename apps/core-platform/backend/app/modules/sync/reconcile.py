"""Draining ``sync.pending_references`` — the other half of DEFER.

A document that named a master we had not synced yet left a row here saying
*"table X, row Y, column Z is waiting for (module, external_id)"*. Once the
owning module syncs, the crosswalk can answer, and this lane writes the foreign
key that was left NULL.

Source-neutral by construction: it resolves through ``sync.sync_records`` and
writes through the waiting row's own table name, so it never learns what Zoho
is. ``.importlinter`` enforces that ``app.modules.sync`` imports no connector
and no feature module.

**Why an UPDATE by primary key and not the ORM.** The waiting table is known
only as a string — that is the whole point of a polymorphic queue — so there is
no mapper to go through. The write is a single-column, single-row UPDATE keyed
on the id we recorded, which is the narrowest statement that can do the job and
cannot touch anything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sync.crosswalk import resolve_many
from app.modules.sync.models import PendingReference

logger = structlog.get_logger("app.sync.reconcile")

#: Tables a waiter may name. Checked before the identifier reaches SQL — the
#: value comes from our own registry, never from a payload, but a queue row is
#: still data and an allow-list is what keeps it from becoming an injection.
_IDENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")


def _safe_identifier(value: str) -> bool:
    return bool(value) and set(value) <= _IDENT and ".." not in value


@dataclass(slots=True)
class DrainReport:
    scanned: int = 0
    linked: int = 0
    still_missing: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"scanned": self.scanned, "linked": self.linked,
                "still_missing": self.still_missing, "skipped": self.skipped}


async def drain_pending_references(
    db: AsyncSession, *, tenant_id: int, source_system: str = "zoho", limit: int = 500,
) -> DrainReport:
    """Resolve what can be resolved; leave the rest for the next pass.

    A still-unresolvable waiter is **kept**, with ``attempts`` incremented: the
    master may simply not have synced yet. The count is the operator-visible
    answer to "what did we fail to link?", which silent NULLs never gave.
    """
    report = DrainReport()
    waiters = (await db.scalars(
        select(PendingReference)
        .where(PendingReference.tenant_id == tenant_id,
               PendingReference.source_system == source_system)
        .order_by(PendingReference.created_at)
        .limit(limit)
    )).all()
    report.scanned = len(waiters)
    if not waiters:
        return report

    pairs = sorted({(w.module, w.external_id) for w in waiters})
    rows = await db.execute(resolve_many(
        tenant_id=tenant_id, source_system=source_system, pairs=pairs,
    ))
    resolved = {(module, external_id): entity_id
                for module, external_id, _table, entity_id, _state in rows}

    linked_ids: list[int] = []
    for waiter in waiters:
        entity_id = resolved.get((waiter.module, waiter.external_id))
        if entity_id is None:
            report.still_missing += 1
            waiter.attempts = (waiter.attempts or 0) + 1
            waiter.last_attempt_at = datetime.now(UTC)
            continue
        if not (_safe_identifier(waiter.waiting_table) and _safe_identifier(waiter.waiting_column)):
            logger.error("sync.reconcile.unsafe_waiter", pending_id=waiter.id,
                         table=waiter.waiting_table, column=waiter.waiting_column)
            report.skipped += 1
            continue
        await db.execute(
            text(f"UPDATE {waiter.waiting_table} SET {waiter.waiting_column} = :entity_id "
                 "WHERE id = :waiting_id"),
            {"entity_id": entity_id, "waiting_id": waiter.waiting_id},
        )
        linked_ids.append(waiter.id)
        report.linked += 1

    if linked_ids:
        await db.execute(delete(PendingReference).where(PendingReference.id.in_(linked_ids)))
    logger.info("sync.reconcile.drained", tenant_id=tenant_id, **report.as_dict())
    return report


async def mark_attempted(db: AsyncSession, ids: list[int]) -> None:
    """Bump ``attempts`` without resolving — for a pass that ran out of budget."""
    if not ids:
        return
    await db.execute(
        update(PendingReference)
        .where(PendingReference.id.in_(ids))
        .values(attempts=PendingReference.attempts + 1, last_attempt_at=datetime.now(UTC))
    )


__all__ = ["DrainReport", "drain_pending_references", "mark_attempted"]
