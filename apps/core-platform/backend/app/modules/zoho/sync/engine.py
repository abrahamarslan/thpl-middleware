"""The Sync Engine — inbound strategies, N+1 handling, nested-entity routing.

Strategies (selected per module by config, overridable per run):

  FULL         paginate the list endpoint (batch_size <= 200/page). When the
               module declares ``detail_required`` the engine solves the N+1
               problem explicitly: every listed record triggers a detail fetch —
               either INLINE (same task, honouring wait_between_calls) or
               QUEUED (one Celery task per record for max throughput).
  INCREMENTAL  same pipeline but windowed by the ``last_modified_time``
               cursor persisted in zoho_sync_stats. Degrades to FULL when a
               module has no modified-since support (e.g. organizations).
  INDEX        list endpoint only — never N+1 — for lightweight modules
               where the index row carries everything we mirror.

Identity matching: ALWAYS by ``zoho_id``. Exists locally -> UPDATE (even if
soft-deleted, so a resurrected Zoho record revives its local row); missing
-> CREATE.

Nested relations: Zoho embeds related records in parent payloads (a Contact
carries a ``currency`` object and ``tax_groups`` array). Before upserting a
parent, the engine routes each embedded payload to its owning module (via
NestedEntityRule), upserts the child FIRST, then stamps the child's local id
/ zoho_id onto the configured parent FK columns.

Failure doctrine:
  - a single bad record logs + counts an error and the run continues;
  - upstream failures (ZohoApiError other than NotFound) abort the run and
    propagate, so the Celery task's autoretry/backoff takes over;
  - every run finishes by upserting zoho_sync_stats, success or not.
"""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.zoho.core.client import ZohoClient, zoho_client
from app.modules.zoho.core.exceptions import ZohoApiError, ZohoNotFoundError
from app.modules.zoho.sync.config import ModuleSyncConfig, SyncDirection, SyncStrategyName
from app.modules.zoho.sync.mapper import (
    MISSING,
    extract,
    flatten_custom_fields,
    map_inbound,
    parse_zoho_datetime,
)
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.models import ZohoQueueLog, ZohoSyncStat
from app.modules.zoho.sync.registry import ZohoModuleDefinition, sync_registry

logger = structlog.get_logger("app.zoho.sync.engine")

_CURSOR_FMT = "%Y-%m-%dT%H:%M:%S%z"  # Zoho's last_modified_time filter format


class SyncRunReport(BaseModel):
    """Outcome of one engine run — returned by Celery tasks and the admin API."""

    module: str
    mode: str
    pages: int = 0
    listed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    queued_details: int = 0
    soft_deleted: int = 0
    duration_ms: int = 0
    cursor: str | None = None
    status: str = "success"  # success | partial | failed


async def record_queue_log(
    db: AsyncSession,
    *,
    module: str,
    operation: str,
    status: str,
    zoho_id: str | None = None,
    local_id: str | None = None,
    error: str | None = None,
    payload: dict | None = None,
    celery_task_id: str | None = None,
    attempt: int = 0,
) -> ZohoQueueLog:
    """Append one row-level journal entry (see models.ZohoQueueLog)."""
    now = datetime.now(UTC)
    ctx = structlog.contextvars.get_contextvars()
    row = ZohoQueueLog(
        module_name=module,
        operation=operation,
        status=status,
        zoho_id=zoho_id,
        local_id=str(local_id) if local_id is not None else None,
        error=error,
        payload=payload,
        celery_task_id=celery_task_id,
        attempt=attempt,
        request_id=ctx.get("request_id"),
        queued_at=now if status == "queued" else None,
        started_at=now if status == "processing" else None,
        finished_at=now if status in ("success", "failed", "skipped") else None,
    )
    db.add(row)
    await db.flush()
    return row


class ZohoSyncEngine:
    """One engine instance per unit of work (request or Celery task)."""

    def __init__(self, db: AsyncSession, client: ZohoClient | None = None) -> None:
        self.db = db
        # Celery tasks inject a fresh client (loop-safety); requests use the singleton.
        self.client = client or zoho_client

    # ── Public entry points ──────────────────────────────────────────────────

    async def run(self, module_name: str, mode: str | None = None) -> SyncRunReport:
        """Execute one sync run for a module. ``mode`` overrides the configured
        strategy (used by the admin API / weekly full-sync beat entry)."""
        defn = sync_registry.get(module_name)
        cfg = defn.config

        if not cfg.enabled or cfg.direction in (SyncDirection.DISABLED, SyncDirection.OUTBOUND):
            return SyncRunReport(module=module_name, mode="skipped", status="success")

        effective = SyncStrategyName(mode) if mode else cfg.strategy
        # Incremental degrades to full when the module has no modified filter.
        if effective is SyncStrategyName.INCREMENTAL and cfg.modified_since_param is None:
            effective = SyncStrategyName.FULL

        report = SyncRunReport(module=module_name, mode=effective.value)
        started = time.perf_counter()
        try:
            await self._run_list_pipeline(defn, effective, report)
            report.status = "success" if report.errors == 0 else "partial"
        except Exception as e:
            report.status = "failed"
            await self._update_stats(defn, report, error=str(e)[:2000])
            raise
        finally:
            report.duration_ms = int((time.perf_counter() - started) * 1000)
        await self._update_stats(defn, report)
        logger.info("zoho_sync_run_complete", **report.model_dump())
        return report

    async def fetch_detail_and_upsert(
        self, module_name: str, zoho_id: str, *, queue_log_id: int | None = None, attempt: int = 0
    ) -> dict:
        """N+1 worker: GET the full record and upsert it (queued dispatch path)."""
        defn = sync_registry.get(module_name)
        log = await self.db.get(ZohoQueueLog, queue_log_id) if queue_log_id else None
        if log:
            log.status, log.started_at, log.attempt = "processing", datetime.now(UTC), attempt
            await self.db.flush()
        try:
            response = await self.client.get(defn.config.detail_path(zoho_id))
            payload = response.data if isinstance(response.data, dict) else None
            if payload is None:
                raise ZohoNotFoundError(f"Empty detail payload for {module_name}/{zoho_id}")
            row, created = await self.upsert_payload(defn, payload, source="detail_fetch")
            if log:
                log.status, log.finished_at, log.local_id = "success", datetime.now(UTC), str(row.id)
            return {"zoho_id": zoho_id, "created": created, "local_id": row.id}
        except ZohoNotFoundError:
            # Deleted upstream between listing and detail fetch — soft-skip.
            if log:
                log.status, log.finished_at, log.error = "skipped", datetime.now(UTC), "gone_upstream"
            logger.warning("zoho_detail_gone", module=module_name, zoho_id=zoho_id)
            return {"zoho_id": zoho_id, "skipped": True}
        except Exception as e:
            if log:
                log.status, log.finished_at, log.error = "failed", datetime.now(UTC), str(e)[:2000]
            raise

    # ── Inbound upsert (the heart of the engine) ────────────────────────────

    async def upsert_payload(
        self, defn: ZohoModuleDefinition, payload: dict, *, source: str
    ) -> tuple[Any, bool]:
        """Map, resolve nested entities, and CREATE-or-UPDATE by zoho_id."""
        cfg = defn.config

        raw_id = extract(payload, cfg.zoho_id_attr)
        if raw_id is MISSING or raw_id in (None, ""):
            raise ValueError(f"payload for '{cfg.module}' lacks id attr '{cfg.zoho_id_attr}'")
        zoho_id = str(raw_id)

        values = map_inbound(cfg, payload)
        values.update(await self._resolve_nested(defn, payload))
        if defn.pre_upsert is not None:
            values = defn.pre_upsert(payload, values) or values

        row = await self._get_by_zoho_id(defn, zoho_id)
        created = row is None
        if created:
            row = defn.model(zoho_id=zoho_id)
            self.db.add(row)
        for column, value in values.items():
            setattr(row, column, value)

        # Raw document + dynamic custom fields (hstore) — always refreshed.
        row.zoho_raw = payload
        custom = flatten_custom_fields(payload)
        if custom is not None:
            row.custom_fields = custom

        row.synced_at = datetime.now(UTC)
        row.sync_status = SyncStatus.SYNCED.value
        row.sync_error = None
        row.append_sync_log("inbound_upsert", source=source, created=created)

        await self.db.flush()
        if defn.post_upsert is not None:
            await defn.post_upsert(row, payload)
        return row, created

    async def _resolve_nested(self, defn: ZohoModuleDefinition, payload: dict) -> dict[str, Any]:
        """Sync embedded child entities first; return parent FK column values."""
        extra: dict[str, Any] = {}
        for rule in defn.config.nested:
            embedded = payload.get(rule.attr)
            if not embedded:
                continue
            try:
                child_defn = sync_registry.get(rule.module)
            except Exception:
                logger.warning("nested_module_unregistered", parent=defn.name, module=rule.module)
                continue
            children = embedded if rule.many and isinstance(embedded, list) else [embedded]
            last_child = None
            for child_payload in children:
                if not isinstance(child_payload, dict):
                    continue
                try:
                    last_child, _ = await self.upsert_payload(child_defn, child_payload, source=f"nested:{defn.name}")
                except Exception:
                    logger.warning("nested_upsert_failed", parent=defn.name, module=rule.module, exc_info=True)
            if last_child is not None and not rule.many:
                if rule.parent_fk:
                    extra[rule.parent_fk] = last_child.id
                if rule.parent_zoho_fk:
                    extra[rule.parent_zoho_fk] = last_child.zoho_id
        return extra

    # ── The list pipeline (full / incremental / index) ──────────────────────

    async def _run_list_pipeline(
        self, defn: ZohoModuleDefinition, mode: SyncStrategyName, report: SyncRunReport
    ) -> None:
        cfg = defn.config
        params: dict[str, Any] = dict(cfg.list_params)
        max_modified: datetime | None = None
        seen_zoho_ids: set[str] = set()

        if mode is SyncStrategyName.INCREMENTAL:
            cursor = await self._get_cursor(defn)
            if cursor:
                params[cfg.modified_since_param] = cursor
            if cfg.sort_column:
                params.update(sort_column=cfg.sort_column, sort_order="A")

        async for page in self.client.paginate(cfg.endpoint, params=params, per_page=cfg.batch_size):
            report.pages += 1
            records = page.data if isinstance(page.data, list) else ([page.data] if page.data else [])
            for record in records:
                report.listed += 1
                raw_id = extract(record, cfg.zoho_id_attr)
                zoho_id = str(raw_id) if raw_id not in (MISSING, None, "") else None
                if zoho_id:
                    seen_zoho_ids.add(zoho_id)
                modified = parse_zoho_datetime(record.get("last_modified_time"))
                if modified and (max_modified is None or modified > max_modified):
                    max_modified = modified
                try:
                    await self._process_listed_record(defn, mode, record, zoho_id, report)
                except ZohoNotFoundError:
                    report.skipped += 1
                except ZohoApiError:
                    raise  # upstream failure — abort, let Celery retry the run
                except Exception as e:  # one bad record never sinks the run
                    report.errors += 1
                    logger.error("zoho_record_sync_failed", module=defn.name, zoho_id=zoho_id, error=str(e))
                    await record_queue_log(
                        self.db, module=defn.name, operation="inbound_upsert",
                        status="failed", zoho_id=zoho_id, error=str(e)[:2000],
                    )

        if max_modified is not None:
            report.cursor = max_modified.strftime(_CURSOR_FMT)

        # Reconciliation: FULL sync may soft-delete rows that vanished upstream.
        if mode is SyncStrategyName.FULL and cfg.soft_delete_missing and seen_zoho_ids:
            report.soft_deleted = await self._soft_delete_missing(defn, seen_zoho_ids)

    async def _process_listed_record(
        self,
        defn: ZohoModuleDefinition,
        mode: SyncStrategyName,
        record: dict,
        zoho_id: str | None,
        report: SyncRunReport,
    ) -> None:
        cfg = defn.config
        needs_detail = cfg.detail_required and mode is not SyncStrategyName.INDEX

        if needs_detail and zoho_id and cfg.detail_dispatch == "queued":
            # Fan out: journal first, then one Celery task per record.
            log = await record_queue_log(
                self.db, module=defn.name, operation="detail_fetch", status="queued", zoho_id=zoho_id
            )
            from app.tasks.zoho_sync import fetch_detail  # lazy: tasks import this module

            async_result = fetch_detail.delay(defn.name, zoho_id, queue_log_id=log.id)
            log.celery_task_id = async_result.id
            report.queued_details += 1
            return

        if needs_detail and zoho_id:
            # Inline N+1: fetch the full record now, pace with wait_between_calls.
            if cfg.wait_between_calls:
                await asyncio.sleep(cfg.wait_between_calls)
            response = await self.client.get(cfg.detail_path(zoho_id))
            record = response.data if isinstance(response.data, dict) else record

        _, created = await self.upsert_payload(defn, record, source=f"list:{mode.value}")
        if created:
            report.created += 1
        else:
            report.updated += 1
        if zoho_id:
            await self._touch_last_id(defn, zoho_id)

    async def _soft_delete_missing(self, defn: ZohoModuleDefinition, seen: set[str]) -> int:
        """Soft-delete local rows whose zoho_id no longer exists upstream."""
        model = defn.model
        stmt = (
            select(model)
            .where(model.zoho_id.is_not(None), model.zoho_id.not_in(seen))
            .execution_options(include_deleted=False)
        )
        rows = (await self.db.scalars(stmt)).all()
        now = datetime.now(UTC)
        for row in rows:
            row.deleted_at = now
            row.sync_status = SyncStatus.DELETED.value
            row.append_sync_log("soft_deleted_missing_upstream")
        await self.db.flush()
        return len(rows)

    # ── Lookups & stats ─────────────────────────────────────────────────────

    async def _get_by_zoho_id(self, defn: ZohoModuleDefinition, zoho_id: str) -> Any | None:
        stmt = (
            select(defn.model)
            .where(defn.model.zoho_id == zoho_id)
            .execution_options(include_deleted=True)  # revive soft-deleted rows on re-sync
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def _get_stat(self, module: str) -> ZohoSyncStat:
        stat = await self.db.scalar(select(ZohoSyncStat).where(ZohoSyncStat.module_name == module))
        if stat is None:
            stat = ZohoSyncStat(module_name=module)
            self.db.add(stat)
            await self.db.flush()
        return stat

    async def _get_cursor(self, defn: ZohoModuleDefinition) -> str | None:
        stat = await self._get_stat(defn.name)
        return stat.last_incremental_cursor

    async def _touch_last_id(self, defn: ZohoModuleDefinition, zoho_id: str) -> None:
        # Cheap in-memory update; persisted with the final stats upsert.
        self._last_zoho_id = zoho_id  # noqa: SLF001 — engine-local scratch

    async def _update_stats(self, defn: ZohoModuleDefinition, report: SyncRunReport, error: str | None = None) -> None:
        try:
            stat = await self._get_stat(defn.name)
            now = datetime.now(UTC)
            stat.last_sync_time = now
            if report.mode == SyncStrategyName.FULL.value:
                stat.last_full_sync_time = now
            if report.cursor:
                stat.last_incremental_cursor = report.cursor
            if getattr(self, "_last_zoho_id", None):
                stat.last_zoho_id_synced = self._last_zoho_id
            stat.total_records_synced = (stat.total_records_synced or 0) + report.created + report.updated
            stat.records_created = (stat.records_created or 0) + report.created
            stat.records_updated = (stat.records_updated or 0) + report.updated
            stat.skipped_records = (stat.skipped_records or 0) + report.skipped
            stat.error_count = (stat.error_count or 0) + report.errors + (1 if error else 0)
            stat.run_count = (stat.run_count or 0) + 1
            stat.last_run_status = "failed" if error else report.status
            stat.last_run_mode = report.mode
            stat.last_run_duration_ms = report.duration_ms
            stat.last_error = error
            await self.db.flush()
        except Exception:  # stats must never mask the real failure
            logger.error("zoho_sync_stats_update_failed", module=defn.name, exc_info=True)
