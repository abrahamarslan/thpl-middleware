"""Batched page apply: one preload query, one flush — and per-record isolation.

Two storage shapes, two statement profiles, both pinned here:

  * the MIRROR path (locations) batches a whole page into one INSERT, because
    gate state lives on the entity row and nothing else has to be written;
  * the CROSSWALK path (taxes) keeps the single preload and the single entity
    flush, but each WRITTEN record also costs one guarded upsert — the
    documented price of the monotonic guard, which cannot be batched because a
    rejected row returns no RETURNING row to map back
    (docs/implementation-plan/sync-crosswalk-redesign.md §3.4a).

Pinning the crosswalk count is the point: a regression that turned the preload
into one query per record would otherwise be invisible until production.
"""

from sqlalchemy import event, func, select

from app.modules.taxes.model import TaxComponent
from app.modules.zoho.control.models import ZohoSyncEvent
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.models import ZohoQueueLog
from tests.zoho_sync.fake_client import FakeZohoClient, make_response


def tax(i: int, **extra) -> dict:
    return {"tax_id": f"77{i:04d}", "tax_name": f"Tax {i}", "tax_percentage": i, "tax_type": "tax", **extra}


def client_with(*pages: list[dict]) -> FakeZohoClient:
    """Taxes: crosswalk shape, index_then_detail. Details echo the index row."""
    client = FakeZohoClient()
    client.stub_list("/settings/taxes", list(pages))
    for page in pages:
        for record in page:
            client.stub("GET", f"/settings/taxes/{record['tax_id']}",
                        make_response(record))
    return client


def user(i: int, **extra) -> dict:
    return {"user_id": f"88{i:04d}", "name": f"User {i}", "email": f"u{i}@example.com", **extra}


def user_client(*records: dict) -> FakeZohoClient:
    """zoho_users: still a MIRROR module (no hooks, no crosswalk) — the
    batching baseline the engine's page apply was built for."""
    client = FakeZohoClient()
    client.stub_list("/users", [list(records)])
    return client


class StatementCounter:
    def __init__(self, db) -> None:
        self.statements: list[str] = []
        self._engine = db.bind.sync_engine
        event.listen(self._engine, "before_cursor_execute", self._record)

    def _record(self, _conn, _cursor, statement, *_args):
        self.statements.append(" ".join(statement.split()))

    def count(self, prefix: str) -> int:
        return sum(1 for s in self.statements if s.startswith(prefix))

    def close(self) -> None:
        event.remove(self._engine, "before_cursor_execute", self._record)


async def test_a_mirror_page_is_one_select_and_one_insert(db):
    counter = StatementCounter(db)
    try:
        report = await ZohoSyncEngine(
            db, user_client(*[user(i) for i in range(50)])
        ).run("users")
        await db.commit()
    finally:
        counter.close()
    assert report.created == 50
    assert counter.count("SELECT zoho_users.") == 1     # the page preload
    assert counter.count("INSERT INTO zoho_users") == 1  # 50 rows, one insertmanyvalues

    events = await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                             .where(ZohoSyncEvent.module == "users"))
    assert events == 50                                     # written after the flush, with local ids
    assert not await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                               .where(ZohoSyncEvent.module == "users",
                                      ZohoSyncEvent.local_id.is_(None)))


async def test_mirror_updates_of_a_page_are_batched_too(db):
    await ZohoSyncEngine(db, user_client(*[user(i) for i in range(20)])).run("users")
    await db.commit()
    counter = StatementCounter(db)
    try:
        report = await ZohoSyncEngine(
            db, user_client(*[user(i, name=f"Renamed {i}") for i in range(20)])
        ).run("users")
        await db.commit()
    finally:
        counter.close()
    assert report.updated == 20
    assert counter.count("SELECT zoho_users.") == 1
    # row_version (optimistic lock) needs a per-row rowcount; asyncpg has no
    # multi-row rowcount, so versioned UPDATEs are sent one per row — still
    # ONE preload SELECT per page, and only rows that changed (docs/tenancy §4).
    assert counter.count("UPDATE zoho_users") == 20


async def test_a_crosswalk_page_preloads_once_and_upserts_per_written_record(db):
    """The documented cost of the guarded upsert — pinned so it cannot grow."""
    counter = StatementCounter(db)
    try:
        report = await ZohoSyncEngine(db, client_with([tax(i) for i in range(10)])).run("taxes")
        await db.commit()
    finally:
        counter.close()

    assert report.created == 10
    # TWO page-level crosswalk reads, not one: _stored_versions decides whether
    # a detail call can be skipped, and _apply_page preloads gate state. They
    # read the same rows and could share one query — a known dedup opportunity,
    # pinned here so it stays a known 2 rather than drifting upward.
    # Plus one lookup per detail apply, since each detail is applied on its own.
    preloads = counter.count("SELECT sync.sync_records.id, sync.sync_records.entity_id")
    assert preloads == 2 + 10, "page-level crosswalk reads grew beyond the documented two"
    # One guarded upsert per WRITTEN record. The stubbed detail is identical to
    # the index row, so the detail phase hashes the same and writes nothing —
    # 10, not 20. That the second phase costs nothing when it learns nothing is
    # the gate doing its job.
    assert counter.count("INSERT INTO sync.sync_records") == 10
    # The entity side still batches: one insert for the page.
    assert counter.count("INSERT INTO tax.tax_components") == 1


async def test_a_database_error_isolates_the_bad_record(db):
    # A negative rate is refused by the codec, so the row reaches the flush with
    # no tax_percentage — NOT NULL fails the page and the one-by-one fallback
    # isolates it (the catalog's `quarantine_record`).
    bad = tax(3, tax_percentage=-1)
    report = await ZohoSyncEngine(db, client_with([tax(1), tax(2), bad, tax(4)])).run("taxes")
    await db.commit()

    assert report.created == 3 and report.errors == 1 and report.status == "partial"
    names = sorted((await db.scalars(select(TaxComponent.tax_name))).all())
    assert names == ["Tax 1", "Tax 2", "Tax 4"]
    failed = await db.scalar(select(ZohoQueueLog).where(ZohoQueueLog.status == "failed"))
    assert failed.zoho_id == "770003"


async def test_a_duplicate_inside_one_page_becomes_one_row(db):
    first, again = tax(9), tax(9, tax_name="Tax 9 (later copy)")
    report = await ZohoSyncEngine(db, client_with([first, again])).run("taxes")
    await db.commit()
    rows = (await db.scalars(select(TaxComponent))).all()
    assert len(rows) == 1 and rows[0].tax_name == "Tax 9 (later copy)"
    assert report.created == 1 and report.updated == 1
