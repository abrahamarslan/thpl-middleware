"""Reading and writing crosswalk rows — the four statements that matter.

    load_page          crosswalk LEFT JOIN entity, one query per page. The join
                       is plain, not polymorphic, because every record in a page
                       belongs to ONE module and therefore ONE entity table —
                       which is what keeps the apply gate's local-soft-delete
                       rule alive after the split (redesign plan §2.7).
    resolve_many       (module, external_id) -> entity_id for a whole page,
                       across EVERY referenced module at once. The one query
                       that replaces N per-table ``zoho_id`` lookups (§1.2).
    upsert_record      one atomic guarded INSERT … ON CONFLICT DO UPDATE (§2.6).
    live_external_ids  the reconciliation scan, off the crosswalk index.

Why the upsert and not a read-modify-write: the scheduled scan, a webhook and a
queued detail-fetch can all apply the same record in the same second. The unique
index stops duplicate ROWS, but a read-modify-write still loses an UPDATE. The
guard below lets the row move only forward in source time, so the loser writes
nothing and raises nothing — no exception, no page-savepoint rollback. It is the
same monotonic fence the apply gate decides in Python, now also enforced by the
database.

Every statement here takes ``tenant_id`` explicitly. The session-level tenancy
filter (app/database/tenancy.py) still applies, but a crosswalk that leaks
across tenants would hand one tenant's rows to another tenant's FK resolution —
that is worth stating twice in the SQL rather than inferring once from context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, Update, and_, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sync.models import SyncRecord, gate_columns

#: Columns the guarded upsert overwrites on conflict. The identity columns
#: (tenant/source/module/external_id) and ``first_seen_at`` are never updated.
_UPSERT_COLUMNS = (
    "organization_id", "connection_id", "entity_table", "entity_id", "link_state",
    "source_modified_at", "raw", "raw_hash", "raw_source", "raw_synced_at",
    "remote_deleted_at", "custom_fields", "comments", "synced_at",
)


def load_page(
    *,
    tenant_id: int,
    source_system: str,
    module: str,
    external_ids: list[str],
    entity_model: type[Any] | None = None,
) -> Select:
    """Gate state for a whole page, with the entity's ``deleted_at`` joined in.

    ``deleted_at`` cannot be denormalised onto the crosswalk: it would drift the
    moment an operator soft-deletes through the API — exactly the case the apply
    gate's "a local delete is not the sync's to undo" rule exists for. So we
    join. One module per page means one entity table, so this is an ordinary
    LEFT JOIN and the polymorphic ``entity_table`` column never enters the SQL.

    Only the gate columns are selected: ``raw`` is TOASTed out of line, and a
    ``SELECT *`` here would de-TOAST a 30 KB document on every payload.
    """
    stmt = select(*gate_columns(), SyncRecord.external_id)
    if entity_model is not None:
        stmt = stmt.add_columns(entity_model.deleted_at.label("entity_deleted_at")).outerjoin(
            entity_model, entity_model.id == SyncRecord.entity_id
        # include_deleted is load-bearing, and not for the reason it looks:
        # the automatic soft-delete criteria turns this LEFT JOIN into an inner
        # one, so a crosswalk row whose entity is soft-deleted drops out of the
        # result ENTIRELY. The engine would then read "no crosswalk row", treat
        # a known record as brand new, and insert a duplicate. (Verified by
        # mutation: removing this fails the locally-deleted-row test.)
        ).execution_options(include_deleted=True)
    return stmt.where(
        SyncRecord.tenant_id == tenant_id,
        SyncRecord.source_system == source_system,
        SyncRecord.module == module,
        SyncRecord.external_id.in_(sorted(set(external_ids))),
    )


def resolve_many(
    *, tenant_id: int, source_system: str, pairs: list[tuple[str, str]]
) -> Select:
    """``(module, external_id)`` → local id, for every referenced module at once.

    This is the statement the whole redesign exists for: one round trip resolves
    an invoice page's taxes, currencies, contacts and items together, instead of
    one query per module against a per-table ``zoho_id`` column.
    """
    return select(
        SyncRecord.module, SyncRecord.external_id,
        SyncRecord.entity_table, SyncRecord.entity_id, SyncRecord.link_state,
    ).where(
        SyncRecord.tenant_id == tenant_id,
        SyncRecord.source_system == source_system,
        tuple_(SyncRecord.module, SyncRecord.external_id).in_(sorted(set(pairs))),
    )


async def upsert_record(
    db: AsyncSession,
    *,
    tenant_id: int,
    source_system: str,
    module: str,
    external_id: str,
    values: dict[str, Any],
) -> tuple[int, int] | None:
    """Write one crosswalk row atomically. Returns ``(id, sync_version)``.

    Returns **None** when the guard rejected the update — another lane applied a
    newer payload for this record first. The caller counts that as
    ``stale_ignored``; it is not an error, and nothing was written.

    ``sync_version`` is incremented by the statement itself, so it stays a true
    count of applied changes under concurrency, and the returned value is the
    evidence that *this* call was the winner.
    """
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source_system": source_system,
        "module": module,
        "external_id": external_id,
        "sync_version": 1,
        **values,
    }
    stmt = pg_insert(SyncRecord).values(**payload)
    excluded = stmt.excluded

    # Monotonic guard: the row may only move forward in the SOURCE's time. An
    # undated payload (Zoho settings endpoints carry no last_modified_time) is
    # always let through — the apply gate's hash check is what decides those.
    guard = or_(
        excluded.source_modified_at.is_(None),
        SyncRecord.source_modified_at.is_(None),
        excluded.source_modified_at >= SyncRecord.source_modified_at,
    )
    updates: dict[str, Any] = {
        name: getattr(excluded, name) for name in _UPSERT_COLUMNS if name in payload
    }
    updates["sync_version"] = SyncRecord.sync_version + 1

    stmt = stmt.on_conflict_do_update(
        index_elements=[
            SyncRecord.tenant_id, SyncRecord.source_system,
            SyncRecord.module, SyncRecord.external_id,
        ],
        set_=updates,
        where=guard,
    ).returning(SyncRecord.id, SyncRecord.sync_version)

    row = (await db.execute(stmt)).first()
    return (row[0], row[1]) if row is not None else None


def live_external_ids(*, tenant_id: int, source_system: str, module: str) -> Select:
    """Every external id we hold live for a module — the reconciliation scan.

    Replaces today's "select every zoho_id from the entity table": one indexed
    read of ``ix_sync_records_module_live``, no entity table touched.
    """
    return select(SyncRecord.external_id).where(
        SyncRecord.tenant_id == tenant_id,
        SyncRecord.source_system == source_system,
        SyncRecord.module == module,
        SyncRecord.remote_deleted_at.is_(None),
    )


def tombstone(
    *, tenant_id: int, source_system: str, module: str, external_ids: list[str], at: datetime
) -> Update:
    """Mark records the source no longer lists as remotely deleted.

    The caller MUST also soft-delete the entity rows in the same transaction:
    the gate reads ``deleted_at`` from the entity and ``remote_deleted_at`` from
    here, and a half-written tombstone breaks the resurrection fence (§2.7).
    """
    return (
        update(SyncRecord)
        .where(
            SyncRecord.tenant_id == tenant_id,
            SyncRecord.source_system == source_system,
            SyncRecord.module == module,
            SyncRecord.external_id.in_(external_ids),
            SyncRecord.remote_deleted_at.is_(None),
        )
        .values(remote_deleted_at=at, sync_version=SyncRecord.sync_version + 1, synced_at=at)
    )


def by_entity(*, tenant_id: int, entity_table: str, entity_ids: list[int]) -> Select:
    """Reverse lookup: what does each source call these local rows?

    Serves "show me this currency's Zoho id" and the orphan sweeper. Uses
    ``ix_sync_records_entity``; fans out across the (few) source partitions,
    which is why that index deliberately leads with ``entity_table``.
    """
    return select(
        SyncRecord.source_system, SyncRecord.module,
        SyncRecord.external_id, SyncRecord.entity_id, SyncRecord.link_state,
    ).where(
        and_(
            SyncRecord.tenant_id == tenant_id,
            SyncRecord.entity_table == entity_table,
            SyncRecord.entity_id.in_(entity_ids),
        )
    )


__all__ = [
    "by_entity",
    "live_external_ids",
    "load_page",
    "resolve_many",
    "tombstone",
    "upsert_record",
]
