"""Bounded slices: stop budgets, per-page commits, resume from the cursor page.

Uses taxes — a paginated module without detail calls (organizations is a
single un-paginated response, ERRORS E29)."""

from sqlalchemy import func, select

from app.modules.zoho.control.config import zoho_config
from app.modules.zoho.control.models import RunStatus, ZohoSyncCursor, ZohoSyncRun
from app.modules.zoho.core.errors import ZohoTransientError
from app.modules.taxes.model import TaxComponent
from app.modules.zoho.sync.registry import sync_registry
from app.tasks.zoho_sync import execute_leased_run
from tests.zoho_sync.fake_client import FakeZohoClient

TAXES = [{"tax_id": str(1000 + i), "tax_name": f"Tax {i}", "tax_percentage": i, "tax_type": "tax"} for i in range(3)]


class PagedClient(FakeZohoClient):
    """Three list pages of one tax each; optionally fails page N once."""

    def __init__(self, fail_page: int | None = None) -> None:
        super().__init__()
        self.stub_list("/settings/taxes", [[tax] for tax in TAXES])
        self.fail_page = fail_page

    async def get(self, path, *, params=None):
        page = (params or {}).get("page")
        if self.fail_page is not None and path == "/settings/taxes" and page == self.fail_page:
            self.fail_page = None
            raise ZohoTransientError("503 from Zoho", http_status=503)
        return await super().get(path, params=params)

    def pages_requested(self) -> list[int]:
        return [c["params"]["page"] for c in self.calls if c["path"] == "/settings/taxes"]


async def run_manual(db, client):
    return await execute_leased_run(db, client, module_name="taxes", lane="manual",
                                    mode="full", trigger="test")


async def tax_count(db) -> int:
    return int(await db.scalar(select(func.count()).select_from(TaxComponent)))


async def cursor(db) -> ZohoSyncCursor:
    db.expire_all()
    return await db.get(ZohoSyncCursor, ("taxes", "manual"))


async def test_page_budget_yields_and_the_next_slice_resumes(db, redis_available):
    await zoho_config.set(db, sync_registry.get("taxes"), "max_pages_per_run", 1, actor="test")

    first = PagedClient()
    result = await run_manual(db, first)
    assert result["status"] == RunStatus.YIELDED and result["next_page"] == 2
    assert result["stop_reason"] == "budget:max_pages"
    assert first.pages_requested() == [1] and await tax_count(db) == 1
    assert (await cursor(db)).next_page == 2

    second = PagedClient()
    result = await run_manual(db, second)
    assert second.pages_requested() == [2] and result["start_page"] == 2
    assert (await cursor(db)).next_page == 3

    third = PagedClient()
    result = await run_manual(db, third)
    assert result["status"] == RunStatus.SUCCEEDED and third.pages_requested() == [3]
    assert await tax_count(db) == 3
    assert (await cursor(db)).next_page == 1                    # scan complete: next scan starts over

    runs = (await db.scalars(select(ZohoSyncRun).order_by(ZohoSyncRun.started_at))).all()
    assert [r.status for r in runs] == [RunStatus.YIELDED, RunStatus.YIELDED, RunStatus.SUCCEEDED]
    assert [r.start_page for r in runs] == [1, 2, 3]


async def test_a_failure_keeps_committed_pages_and_resumes_at_the_failed_one(db, redis_available):
    failing = PagedClient(fail_page=2)
    try:
        await run_manual(db, failing)
    except ZohoTransientError:
        pass
    else:  # pragma: no cover
        raise AssertionError("the transient error must propagate to Celery's retry policy")

    assert await tax_count(db) == 1                             # page 1 survived the failure
    assert (await cursor(db)).next_page == 2
    failed = await db.scalar(select(ZohoSyncRun))
    assert failed.status == RunStatus.FAILED and failed.pages == 1 and failed.created == 1

    retry = PagedClient()
    result = await run_manual(db, retry)
    assert retry.pages_requested() == [2, 3]
    assert result["status"] == RunStatus.SUCCEEDED and await tax_count(db) == 3


async def test_a_different_mode_does_not_resume_anothers_scan(db, redis_available):
    await zoho_config.set(db, sync_registry.get("taxes"), "max_pages_per_run", 1, actor="test")
    await run_manual(db, PagedClient())                          # full scan yields at page 2

    index_client = PagedClient()
    await execute_leased_run(db, index_client, module_name="taxes", lane="manual",
                             mode="index", trigger="test")
    assert index_client.pages_requested() == [1]                # starts its own scan
