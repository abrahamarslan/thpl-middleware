"""Batched page apply: one preload query, one flush — and per-record isolation on failure."""

from sqlalchemy import event, func, select

from app.modules.taxes.model import ZohoTax
from app.modules.zoho.control.models import ZohoSyncEvent
from app.modules.zoho.sync.engine import ZohoSyncEngine
from app.modules.zoho.sync.models import ZohoQueueLog
from tests.zoho_sync.fake_client import FakeZohoClient


def tax(i: int, **extra) -> dict:
    return {"tax_id": f"77{i:04d}", "tax_name": f"Tax {i}", "tax_percentage": i, "tax_type": "tax", **extra}


def client_with(*pages: list[dict]) -> FakeZohoClient:
    client = FakeZohoClient()
    client.stub_list("/settings/taxes", list(pages))
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


async def test_a_page_is_one_select_and_one_insert(db):
    counter = StatementCounter(db)
    try:
        report = await ZohoSyncEngine(db, client_with([tax(i) for i in range(50)])).run("taxes")
        await db.commit()
    finally:
        counter.close()
    assert report.created == 50
    assert counter.count("SELECT zoho_taxes.") == 1          # the page preload
    assert counter.count("INSERT INTO zoho_taxes") == 1      # 50 rows, one statement (insertmanyvalues)

    events = await db.scalar(select(func.count()).select_from(ZohoSyncEvent).where(ZohoSyncEvent.module == "taxes"))
    assert events == 50                                     # events written after the flush, with local ids
    assert not await db.scalar(select(func.count()).select_from(ZohoSyncEvent)
                               .where(ZohoSyncEvent.module == "taxes", ZohoSyncEvent.local_id.is_(None)))


async def test_updates_of_a_page_are_batched_too(db):
    await ZohoSyncEngine(db, client_with([tax(i) for i in range(20)])).run("taxes")
    await db.commit()
    counter = StatementCounter(db)
    try:
        report = await ZohoSyncEngine(db, client_with([tax(i, tax_name=f"Renamed {i}") for i in range(20)])).run("taxes")
        await db.commit()
    finally:
        counter.close()
    assert report.updated == 20
    assert counter.count("SELECT zoho_taxes.") == 1
    # row_version (optimistic lock) needs a per-row rowcount; asyncpg has no
    # multi-row rowcount, so versioned UPDATEs are sent one per row — still
    # ONE preload SELECT per page, and only rows that changed (docs/tenancy §4).
    assert counter.count("UPDATE zoho_taxes") == 20


async def test_a_database_error_isolates_the_bad_record(db):
    bad = tax(3, country_code="THIS-IS-TOO-LONG")            # varchar(8): the page flush fails
    report = await ZohoSyncEngine(db, client_with([tax(1), tax(2), bad, tax(4)])).run("taxes")
    await db.commit()

    assert report.created == 3 and report.errors == 1 and report.status == "partial"
    names = sorted((await db.scalars(select(ZohoTax.tax_name))).all())
    assert names == ["Tax 1", "Tax 2", "Tax 4"]
    failed = await db.scalar(select(ZohoQueueLog).where(ZohoQueueLog.status == "failed"))
    assert failed.zoho_id == "770003"


async def test_a_duplicate_inside_one_page_becomes_one_row(db):
    first, again = tax(9), tax(9, tax_name="Tax 9 (later copy)")
    report = await ZohoSyncEngine(db, client_with([first, again])).run("taxes")
    await db.commit()
    rows = (await db.scalars(select(ZohoTax))).all()
    assert len(rows) == 1 and rows[0].tax_name == "Tax 9 (later copy)"
    assert report.created == 1 and report.updated == 1
