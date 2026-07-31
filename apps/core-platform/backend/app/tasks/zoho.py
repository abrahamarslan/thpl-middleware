"""Zoho synchronisation tasks (queue: integrations).

All Zoho I/O goes through ZohoSyncClient (app.modules.zoho.core), which
shares the token cache / refresh lock / rate-limit window with the API
process — workers and API always act as ONE Zoho client.

Retry model: the client already retries 401/429/5xx/network internally.
Task-level autoretry is the outer safety net for longer Zoho outages
(circuit open, retries exhausted) with exponential backoff.
"""

import structlog
from celery import shared_task

from app.modules.zoho.core import ZohoApiError, zoho_sync_client

logger = structlog.get_logger("app.tasks.zoho")


@shared_task(
    name="app.tasks.zoho.sync_items",
    autoretry_for=(ZohoApiError,),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)
def sync_items() -> dict:
    """Pull the item catalog (prices/stock) page by page.

    Currently warms the pipeline and logs counts; the implementation guide
    (docs/zoho-module-implementation-guide.md) shows how to upsert into
    local mirror tables, which Debezium then streams to ClickHouse.
    """
    total = 0
    for page in zoho_sync_client.paginate("/items"):
        total += len(page.data or [])
    logger.info("zoho_items_synced", count=total)
    return {"synced": total}


@shared_task(
    name="app.tasks.zoho.sync_contacts",
    autoretry_for=(ZohoApiError,),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=5,
)
def sync_contacts() -> dict:
    total = 0
    for page in zoho_sync_client.paginate("/contacts"):
        total += len(page.data or [])
    logger.info("zoho_contacts_synced", count=total)
    return {"synced": total}
