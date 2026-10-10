"""First full sync of Zoho contacts → parties, as consecutive leased slices (temporary; delete after use).

Each slice is one leased run on the manual lane (the engine yields after ~one page; the cursor resumes).
A rate limit (429 / Zoho code 43/44) keeps the page's progress (engine halt) and this loop waits 20 min
before the next slice. Progress: /tmp/parties_sync.log.
"""

import asyncio
import importlib
import time
from datetime import UTC, datetime

LOG = "/tmp/parties_sync.log"


def log(msg: str) -> None:
    with open(LOG, "a") as fh:
        fh.write(f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}\n")


async def main() -> None:
    importlib.import_module("app.router")
    from app.database.db import async_session_factory, engine
    from app.database.redis import redis_client
    from app.modules.zoho.control.planner import LANE_MANUAL, LANE_PRIORITY
    from app.modules.zoho.core.exceptions import ZohoRateLimitedError
    from app.modules.zoho.core.transport import ZohoClient
    from app.tasks.zoho_sync import execute_leased_run

    failures, started = 0, time.time()
    log("first sync started")
    try:
        for slice_no in range(1, 400):
            client = ZohoClient(default_priority=LANE_PRIORITY[LANE_MANUAL], default_module="parties")
            try:
                async with async_session_factory() as db:
                    result = await execute_leased_run(db, client, module_name="parties", lane=LANE_MANUAL,
                                                      mode=None, trigger="cli")
                failures = 0
                log(f"slice {slice_no}: {result.get('status')} pages={result.get('pages')} listed={result.get('listed')} "
                    f"created={result.get('created')} updated={result.get('updated')} unchanged={result.get('unchanged')} "
                    f"errors={result.get('errors')} next_page={result.get('next_page')} stop={result.get('stop_reason')}")
                if str(result.get("status")) not in ("yielded", "RunStatus.YIELDED"):
                    if str(result.get("status")).endswith("skipped") or result.get("status") == "skipped":
                        await asyncio.sleep(60)
                        continue
                    break
            except ZohoRateLimitedError as exc:
                log(f"slice {slice_no}: rate limited ({type(exc).__name__}: {str(exc)[:120]}) — waiting 20 min")
                await asyncio.sleep(1200)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                log(f"slice {slice_no}: FAILED {type(exc).__name__}: {str(exc)[:300]}")
                if failures >= 3:
                    log("three consecutive failures — stopping")
                    break
                await asyncio.sleep(120)
            finally:
                await client.aclose()
    finally:
        log(f"first sync loop finished after {int(time.time() - started)} s")
        await redis_client.aclose()
        await engine.dispose()


asyncio.run(main())
