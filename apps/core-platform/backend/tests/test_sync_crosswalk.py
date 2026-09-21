"""The sync crosswalk: identity, the guarded upsert, and cross-module resolution.

The lost-update test here is the one that matters. The obvious assertion — "two
concurrent applies leave one row" — passes even when an UPDATE is silently lost,
because the unique index guarantees the row count regardless. What has to be
proved is that the *newer* payload's data survives and the older one writes
nothing (docs/implementation-plan/sync-crosswalk-redesign.md §2.6).
"""

from datetime import UTC, datetime

from sqlalchemy import func, select, text

from app.core.conf import settings
from app.modules.sync.crosswalk import (
    by_entity,
    live_external_ids,
    load_page,
    resolve_many,
    tombstone,
    upsert_record,
)
from app.modules.sync.models import LinkState, SyncRecord
from app.modules.tenants.model import Tenant

ZOHO = "zoho"
ENTITY = "currency.currencies"


async def _tenant_id(db) -> int:
    return (await db.scalar(
        select(Tenant).where(Tenant.tenant_code == settings.DEFAULT_TENANT_CODE)
    )).id


def _values(*, entity_id: int, modified: datetime | None, digest: bytes, **kw) -> dict:
    return {
        "entity_table": ENTITY,
        "entity_id": entity_id,
        "link_state": LinkState.LINKED,
        "source_modified_at": modified,
        "raw_hash": digest,
        "raw_source": "list:full",
        "synced_at": datetime.now(UTC),
        **kw,
    }


async def _upsert(db, tenant_id: int, external_id: str, **kw):
    return await upsert_record(
        db, tenant_id=tenant_id, source_system=ZOHO, module="currencies",
        external_id=external_id, values=_values(**kw),
    )


# ── identity ────────────────────────────────────────────────────────────────

async def test_one_crosswalk_row_per_source_record(db):
    tenant_id = await _tenant_id(db)
    first = await _upsert(db, tenant_id, "C1", entity_id=101,
                          modified=datetime(2026, 9, 1, tzinfo=UTC), digest=b"a")
    second = await _upsert(db, tenant_id, "C1", entity_id=101,
                           modified=datetime(2026, 9, 2, tzinfo=UTC), digest=b"b")
    await db.flush()

    assert first is not None and second is not None
    assert first[0] == second[0], "the same external id must reuse its crosswalk row"
    count = await db.scalar(
        select(func.count()).select_from(SyncRecord).where(SyncRecord.external_id == "C1")
    )
    assert count == 1


async def test_the_row_is_routed_to_its_source_partition(db):
    """LIST (source_system) is what makes the gate's lookups prunable."""
    tenant_id = await _tenant_id(db)
    await _upsert(db, tenant_id, "C-PART", entity_id=1, modified=None, digest=b"a")
    await db.flush()

    partition = await db.scalar(text(
        "SELECT tableoid::regclass::text FROM sync.sync_records WHERE external_id = 'C-PART'"
    ))
    assert partition == "sync.sync_records_zoho"


# ── the guard (§2.6) ────────────────────────────────────────────────────────

async def test_an_older_payload_cannot_overwrite_a_newer_one(db):
    """The lost-update regression. An older lane must write NOTHING."""
    tenant_id = await _tenant_id(db)
    newer = datetime(2026, 9, 21, 10, tzinfo=UTC)
    older = datetime(2026, 9, 20, 10, tzinfo=UTC)

    won = await _upsert(db, tenant_id, "C2", entity_id=7, modified=newer, digest=b"newer")
    assert won is not None and won[1] == 1

    lost = await _upsert(db, tenant_id, "C2", entity_id=7, modified=older, digest=b"older")
    assert lost is None, "the older payload was applied — the monotonic guard is broken"
    await db.flush()

    row = await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "C2"))
    assert bytes(row.raw_hash) == b"newer"
    assert row.source_modified_at == newer
    assert row.sync_version == 1, "a rejected write must not burn a version"


async def test_a_newer_payload_wins_and_counts_one_version(db):
    tenant_id = await _tenant_id(db)
    await _upsert(db, tenant_id, "C3", entity_id=8,
                  modified=datetime(2026, 9, 20, tzinfo=UTC), digest=b"old")
    result = await _upsert(db, tenant_id, "C3", entity_id=8,
                           modified=datetime(2026, 9, 22, tzinfo=UTC), digest=b"new")
    await db.flush()

    assert result is not None and result[1] == 2
    row = await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "C3"))
    assert bytes(row.raw_hash) == b"new" and row.sync_version == 2


async def test_an_undated_payload_is_always_let_through(db):
    """Zoho settings endpoints carry no last_modified_time; the gate's hash
    check decides those, so the SQL guard must not fence them out."""
    tenant_id = await _tenant_id(db)
    await _upsert(db, tenant_id, "C4", entity_id=9, modified=None, digest=b"first")
    result = await _upsert(db, tenant_id, "C4", entity_id=9, modified=None, digest=b"second")
    await db.flush()

    assert result is not None
    row = await db.scalar(select(SyncRecord).where(SyncRecord.external_id == "C4"))
    assert bytes(row.raw_hash) == b"second"


# ── resolution (§1.2) ───────────────────────────────────────────────────────

async def test_one_query_resolves_references_across_every_module(db):
    """The statement the redesign exists for: many modules, one round trip."""
    tenant_id = await _tenant_id(db)
    await upsert_record(db, tenant_id=tenant_id, source_system=ZOHO, module="currencies",
                        external_id="900", values=_values(entity_id=11, modified=None, digest=b"c"))
    await upsert_record(db, tenant_id=tenant_id, source_system=ZOHO, module="taxes",
                        external_id="901", values=_values(entity_id=22, modified=None, digest=b"t",
                                                          entity_table="zoho_taxes"))
    await db.flush()

    rows = (await db.execute(resolve_many(
        tenant_id=tenant_id, source_system=ZOHO,
        pairs=[("currencies", "900"), ("taxes", "901"), ("taxes", "missing")],
    ))).all()

    resolved = {(module, external_id): entity_id for module, external_id, _, entity_id, _ in rows}
    assert resolved == {("currencies", "900"): 11, ("taxes", "901"): 22}, (
        "a miss must simply be absent, so the caller can apply its on_missing policy"
    )


async def test_reverse_lookup_finds_what_the_source_calls_a_local_row(db):
    tenant_id = await _tenant_id(db)
    await _upsert(db, tenant_id, "C5", entity_id=55, modified=None, digest=b"a")
    await db.flush()

    rows = (await db.execute(
        by_entity(tenant_id=tenant_id, entity_table=ENTITY, entity_ids=[55])
    )).all()
    assert [(r[0], r[1], r[2]) for r in rows] == [(ZOHO, "currencies", "C5")]


# ── reconciliation (§2.7) ───────────────────────────────────────────────────

async def test_live_ids_come_from_the_crosswalk_not_the_entity_table(db):
    tenant_id = await _tenant_id(db)
    await _upsert(db, tenant_id, "L1", entity_id=1, modified=None, digest=b"a")
    await _upsert(db, tenant_id, "L2", entity_id=2, modified=None, digest=b"b")
    await db.flush()

    ids = set((await db.scalars(
        live_external_ids(tenant_id=tenant_id, source_system=ZOHO, module="currencies")
    )).all())
    assert {"L1", "L2"} <= ids

    await db.execute(tombstone(tenant_id=tenant_id, source_system=ZOHO, module="currencies",
                               external_ids=["L2"], at=datetime.now(UTC)))
    await db.flush()

    ids_after = set((await db.scalars(
        live_external_ids(tenant_id=tenant_id, source_system=ZOHO, module="currencies")
    )).all())
    assert "L1" in ids_after and "L2" not in ids_after


async def test_the_page_loader_selects_only_gate_columns(db):
    """``raw`` is TOASTed; a page load that dragged it in would de-TOAST a
    document per payload. The gate's SELECT list must stay explicit (§2.1)."""
    stmt = load_page(tenant_id=1, source_system=ZOHO, module="currencies",
                     external_ids=["A", "B"])
    selected = {column.name for column in stmt.selected_columns}
    assert "raw" not in selected
    assert {"raw_hash", "source_modified_at", "remote_deleted_at", "external_id"} <= selected
