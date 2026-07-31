"""Outbound sync — the transactional-outbox pattern (local -> Zoho).

Flow (all three operations):

  1. The module service writes the LOCAL change first (create with a NULL
     zoho_id / update columns / soft-delete) inside the request transaction.
  2. ``queue_outbound`` journals the intent into zoho_queue_logs (same
     transaction — the outbox record commits atomically with the change).
  3. A Celery task (app/tasks/zoho_sync.push_outbound) picks the intent up,
     builds the Zoho payload from the module's field map, calls Zoho, and:
       create -> extracts the freshly generated id and back-fills zoho_id
       update -> PUTs to /{endpoint}/{zoho_id}
       delete -> DELETEs and marks the row sync_status='deleted'
  4. Failures increment sync_attempt_count / set sync_error on the row and
     re-raise so Celery's backoff retries take over (bounded by the module's
     retry_limit).

If the task fires before the request transaction commits (rare but possible
with eager brokers), the worker simply retries — the queue-log row is the
handshake.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import ConflictError, NotFoundError
from app.modules.zoho.core.client import ZohoClient
from app.modules.zoho.sync.config import SyncDirection
from app.modules.zoho.sync.engine import record_queue_log
from app.modules.zoho.sync.mapper import extract, map_outbound
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.models import ZohoQueueLog
from app.modules.zoho.sync.registry import sync_registry

logger = structlog.get_logger("app.zoho.sync.outbox")

_OUTBOUND_OPS = ("create", "update", "delete")


async def queue_outbound(db: AsyncSession, module_name: str, local_id: Any, op: str) -> ZohoQueueLog:
    """Journal an outbound intent and enqueue the push task.

    Call INSIDE the same transaction as the local write; the Celery enqueue
    happens immediately (the worker retries until the row is visible).
    """
    if op not in _OUTBOUND_OPS:
        raise ValueError(f"invalid outbound op '{op}'")
    defn = sync_registry.get(module_name)
    if defn.config.direction not in (SyncDirection.OUTBOUND, SyncDirection.BIDIRECTIONAL):
        raise ConflictError(f"module '{module_name}' is not configured for outbound sync")

    log = await record_queue_log(
        db, module=module_name, operation=f"outbound_{op}", status="queued", local_id=str(local_id)
    )

    from app.tasks.zoho_sync import push_outbound  # lazy — tasks import this package

    async_result = push_outbound.apply_async(
        kwargs={"module_name": module_name, "local_id": local_id, "op": op, "queue_log_id": log.id},
        countdown=2,  # small grace period for the caller's commit
    )
    log.celery_task_id = async_result.id
    await db.flush()
    logger.info("zoho_outbound_queued", module=module_name, local_id=local_id, op=op, task_id=async_result.id)
    return log


async def push_record(
    db: AsyncSession,
    client: ZohoClient,
    module_name: str,
    local_id: Any,
    op: str,
    *,
    queue_log_id: int | None = None,
    attempt: int = 0,
) -> dict:
    """Execute one outbound push (runs inside the Celery worker)."""
    defn = sync_registry.get(module_name)
    cfg = defn.config

    log = await db.get(ZohoQueueLog, queue_log_id) if queue_log_id else None
    if log:
        log.status, log.started_at, log.attempt = "processing", datetime.now(UTC), attempt
        await db.flush()

    # include_deleted: a soft-deleted row must still be found to push its delete.
    row = await db.get(defn.model, local_id, execution_options={"include_deleted": True})
    if row is None:
        # Likely enqueued before the request transaction committed.
        raise NotFoundError(f"{module_name} row {local_id} not visible yet")

    try:
        result = await _dispatch(client, defn, row, op)
        row.synced_at = datetime.now(UTC)
        row.sync_status = SyncStatus.DELETED.value if op == "delete" else SyncStatus.SYNCED.value
        row.sync_error = None
        row.append_sync_log(f"outbound_{op}", zoho_id=row.zoho_id)
        if log:
            log.status, log.finished_at, log.zoho_id = "success", datetime.now(UTC), row.zoho_id
        await db.flush()
        return result
    except Exception as e:
        row.sync_attempt_count = (row.sync_attempt_count or 0) + 1
        row.sync_status = SyncStatus.ERROR.value
        row.sync_error = str(e)[:2000]
        row.append_sync_log(f"outbound_{op}_failed", error=str(e)[:500])
        if log:
            log.status, log.finished_at, log.error = "failed", datetime.now(UTC), str(e)[:2000]
        await db.flush()
        raise


async def _dispatch(client: ZohoClient, defn, row, op: str) -> dict:
    cfg = defn.config
    if op == "create":
        payload = map_outbound(cfg, row)
        response = await client.post(cfg.endpoint, json=payload)
        new_id = _extract_new_id(cfg, response.data)
        if new_id is None:
            raise ConflictError(f"Zoho create for '{cfg.module}' returned no {cfg.zoho_id_attr}")
        row.zoho_id = new_id
        return {"op": op, "zoho_id": new_id}

    if row.zoho_id is None:
        # Update/delete before the create ever reached Zoho — escalate to create.
        if op == "update":
            return await _dispatch(client, defn, row, "create")
        return {"op": op, "skipped": "never_pushed"}

    if op == "update":
        payload = map_outbound(cfg, row)
        await client.put(cfg.detail_path(row.zoho_id), json=payload)
        return {"op": op, "zoho_id": row.zoho_id}

    # delete
    await client.delete(cfg.detail_path(row.zoho_id))
    return {"op": op, "zoho_id": row.zoho_id}


def _extract_new_id(cfg, data: Any) -> str | None:
    """Pull the generated id out of Zoho's create response.

    Zoho returns the created resource under its singular key — the core
    client already strips the envelope, so ``data`` is usually the resource
    dict itself; be liberal in what we accept.
    """
    if isinstance(data, dict):
        from app.modules.zoho.sync.mapper import MISSING

        value = extract(data, cfg.zoho_id_attr)
        if value not in (MISSING, None, ""):
            return str(value)
        for nested in data.values():  # e.g. {"organization": {...}}
            if isinstance(nested, dict):
                value = extract(nested, cfg.zoho_id_attr)
                if value not in (MISSING, None, ""):
                    return str(value)
    return None
