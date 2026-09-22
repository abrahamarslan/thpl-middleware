"""The Sync Engine — inbound strategies, N+1 handling, nested-entity routing.

Strategies (selected per module by config, overridable per run):

  FULL         paginate the list endpoint (batch_size <= 200/page). When the
               module declares ``detail_required`` the engine solves the N+1
               problem explicitly: every listed record triggers a detail fetch —
               either INLINE (same task, honouring wait_between_calls) or
               QUEUED (one Celery task per record for max throughput) — unless
               the stored row is already at the listed version (no call spent).
  INCREMENTAL  same pipeline but windowed by the ``last_modified_time``
               cursor persisted in zoho_sync_stats. Degrades to FULL when a
               module has no modified-since support (e.g. organizations).
  INDEX        list endpoint only — never N+1 — for lightweight modules
               where the index row carries everything we mirror.

Every write goes through the **apply gate** (sync/apply.py): a payload older
than the stored version is ignored, an identical one causes no UPDATE, a thin
list row never overwrites a detail document, and a sync tombstone is revived
only by newer evidence (docs/zoho-sync-implementation/apply-gate.md).

**When to stop.** A run is a bounded slice: after each page it checks
``max_run_seconds`` / ``max_pages_per_run`` / ``max_records_per_run`` and, if
one is hit while Zoho still has pages, ends ``yielded`` with ``next_page`` so
the next slice resumes there. The caller's ``page_hook`` (the leased runner)
commits each page, advances the fenced cursor and heartbeats the lease.

**Batched apply (Phase 5).** A page is applied in two phases: first every
record is *materialised* (detail fetched, skipped or queued — per-record error
isolation), then all payloads go through the gate against rows loaded with
ONE query, and the page is written with ONE flush (SQLAlchemy batches the
INSERTs with RETURNING and groups UPDATEs by column set). Sync events and
post-upsert hooks run after that flush, when every row has its id. A database
error in the batch rolls back only the page's savepoint and the page is
re-applied record by record, so one bad row still cannot sink the run.

Identity matching: ALWAYS by ``zoho_id`` (soft-deleted rows included, so a
resurrected Zoho record revives its local row instead of duplicating it).

Nested relations: Zoho embeds related records in parent payloads (a Contact
carries a ``currency`` object and ``tax_groups`` array). Before upserting a
parent, the engine routes each embedded payload to its owning module (via
NestedEntityRule), upserts the child FIRST, then stamps the child's local id
/ zoho_id onto the configured parent FK columns.

Failure doctrine:
  - a single bad record logs + counts an error and the run continues;
  - upstream failures (ZohoApiError other than NotFound) abort the run and
    propagate, so the leased runner / Celery policy takes over;
  - every run finishes by upserting zoho_sync_stats, success or not.
"""

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.tenancy import write_tenant_id
from app.modules.sync.crosswalk import live_external_ids as crosswalk_live_ids
from app.modules.sync.crosswalk import load_page as crosswalk_load_page
from app.modules.sync.crosswalk import resolve_many
from app.modules.sync.crosswalk import tombstone as crosswalk_tombstone
from app.modules.sync.crosswalk import upsert_record
from app.modules.sync.models import LinkState, PendingReference, SyncPayload, SyncRecord
from app.modules.sync.references import Budget, Plan, pairs_in_page, plan_references
from app.modules.sync.translation import PayloadShape
from app.modules.zoho.control.events import build_diff
from app.modules.zoho.control.events import enabled_for as events_enabled_for
from app.modules.zoho.control.events import new_event as new_sync_event
from app.modules.zoho.core.client import ZohoClient, zoho_client
from app.modules.zoho.core.exceptions import ZohoApiError, ZohoNotFoundError
from app.modules.zoho.sync.apply import (
    Decision,
    Incoming,
    Outcome,
    RowState,
    decide,
    payload_hash,
    provenance_rank,
)
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName
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

#: Legacy push states an inbound apply must not overwrite (a local change is
#: still on its way to Zoho, or its failure must stay visible).
_PUSH_PENDING = frozenset({SyncStatus.QUEUED.value, SyncStatus.SYNCING.value, SyncStatus.ERROR.value})


class SyncRunReport(BaseModel):
    """Outcome of one engine run — returned by Celery tasks and the admin API."""

    module: str
    mode: str
    pages: int = 0
    listed: int = 0
    created: int = 0
    updated: int = 0
    resurrected: int = 0
    unchanged: int = 0
    stale_ignored: int = 0
    skipped: int = 0
    errors: int = 0
    queued_details: int = 0
    details_saved: int = 0          # detail calls avoided: row already at the listed version
    soft_deleted: int = 0
    duration_ms: int = 0
    cursor: str | None = None
    start_page: int = 1
    next_page: int | None = None    # set when the slice stopped before the scan ended
    stop_reason: str | None = None  # budget:max_run_seconds | budget:max_pages | budget:max_records
    status: str = "success"         # success | partial | yielded | failed


#: ``page_hook(report, next_page)`` — called after every applied page.
#: ``next_page`` is 1 when the scan is complete.
PageHook = Callable[[SyncRunReport, int], Awaitable[None]]


@dataclasses.dataclass(frozen=True, slots=True)
class ApplyResult:
    row: Any
    outcome: Outcome
    decision: Decision

    @property
    def created(self) -> bool:
        return self.outcome is Outcome.INSERTED


@dataclasses.dataclass(frozen=True, slots=True)
class _StoredVersion:
    modified: datetime | None
    source: str | None
    tombstoned: bool


@dataclasses.dataclass(frozen=True, slots=True)
class _CrosswalkState:
    """One crosswalk row's gate state, plus the entity's own ``deleted_at``.

    The two halves come from one joined query: the sync's view of the record
    (``remote_deleted_at``) lives on the crosswalk, a user's delete
    (``entity_deleted_at``) lives on the entity, and the apply gate needs both
    to tell "Zoho deleted it" from "we deleted it" (redesign plan §2.7).
    """

    id: int
    entity_id: int | None
    entity_table: str
    link_state: str
    source_modified_at: datetime | None
    raw_hash: bytes | None
    raw_source: str | None
    remote_deleted_at: datetime | None
    sync_version: int
    entity_deleted_at: datetime | None = None

    @classmethod
    def of(cls, mapping: Any) -> "_CrosswalkState":
        return cls(
            id=mapping["id"],
            entity_id=mapping["entity_id"],
            entity_table=mapping["entity_table"],
            link_state=mapping["link_state"],
            source_modified_at=mapping["source_modified_at"],
            raw_hash=mapping["raw_hash"],
            raw_source=mapping["raw_source"],
            remote_deleted_at=mapping["remote_deleted_at"],
            sync_version=mapping["sync_version"],
            entity_deleted_at=mapping.get("entity_deleted_at"),
        )


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

    def __init__(self, db: AsyncSession, client: ZohoClient | None = None, *, run_id=None) -> None:
        self.db = db
        # Celery tasks inject a fresh client (loop-safety); requests use the singleton.
        self.client = client or zoho_client
        # Set when the run holds a lease (control plane); stamped on every sync event.
        self.run_id = run_id
        #: The report of the current/last run — readable after an exception.
        self.report: SyncRunReport | None = None
        # Page-batch state (see _apply_page): rows preloaded for the page,
        # and events/hooks that need row ids, run after the page flush.
        self._row_cache: dict[tuple[str, str], Any] | None = None
        self._pending_events: list[tuple[ZohoModuleDefinition, Any, dict]] | None = None
        self._pending_hooks: list[tuple[Any, Any, dict]] = []
        # Crosswalk shape: preloaded gate state, which modules the preload
        # covered, and the rows whose entity id only exists after the flush.
        self._state_cache: dict[tuple[str, str], _CrosswalkState] | None = None
        self._state_loaded: set[str] = set()
        self._pending_links: list[tuple[int, str, Any, Any]] = []
        #: index_then_detail: ids listed this page whose detail is still owed.
        self._detail_backlog: list[str] = []
        # Reference resolution (redesign §4). The budget and the single-flight
        # set are per RUN, not per page: a ceiling that reset every page would
        # not be a ceiling. The cache is per page.
        self._reference_cache: dict[tuple[str, str], int | None] | None = None
        self._reference_budget: Budget | None = None
        self._reference_attempted: set[tuple[str, str]] = set()
        self._pending_reference_writes: list[tuple[ZohoModuleDefinition, Any, Any, str]] = []

    # ── Public entry points ──────────────────────────────────────────────────

    async def resolve(self, module_name: str) -> ZohoModuleDefinition:
        """The module definition with runtime config overrides applied."""
        from app.modules.zoho.control.config import zoho_config

        defn = sync_registry.get(module_name)
        effective = await zoho_config.effective(self.db, defn)
        return defn if effective is defn.config else dataclasses.replace(defn, config=effective)

    async def run(
        self,
        module_name: str,
        mode: str | None = None,
        *,
        start_page: int = 1,
        page_hook: PageHook | None = None,
    ) -> SyncRunReport:
        """Execute one sync slice for a module. ``mode`` overrides the configured
        strategy (lanes / admin API); ``start_page`` resumes a yielded scan."""
        defn = await self.resolve(module_name)
        cfg = defn.config

        if not cfg.enabled or cfg.direction in (SyncDirection.DISABLED, SyncDirection.OUTBOUND):
            self.report = SyncRunReport(module=module_name, mode="skipped", status="success")
            return self.report

        effective = SyncStrategyName(mode) if mode else cfg.strategy
        # Incremental degrades to full when the module has no modified filter.
        if effective is SyncStrategyName.INCREMENTAL and cfg.modified_since_param is None:
            effective = SyncStrategyName.FULL

        report = SyncRunReport(module=module_name, mode=effective.value, start_page=max(start_page, 1))
        self.report = report
        started = time.perf_counter()
        try:
            await self._run_list_pipeline(defn, effective, report, started=started, page_hook=page_hook)
            if report.next_page is not None:
                report.status = "yielded"
            else:
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
        defn = await self.resolve(module_name)
        log = await self.db.get(ZohoQueueLog, queue_log_id) if queue_log_id else None
        if log:
            log.status, log.started_at, log.attempt = "processing", datetime.now(UTC), attempt
            await self.db.flush()
        try:
            response = await self.client.get(defn.config.detail_path(zoho_id), **_api_kw(defn.config))
            payload = response.data if isinstance(response.data, dict) else None
            if payload is None:
                raise ZohoNotFoundError(f"Empty detail payload for {module_name}/{zoho_id}")
            result = await self.apply_payload(defn, payload, source="detail_fetch")
            if log:
                log.status, log.finished_at, log.local_id = "success", datetime.now(UTC), str(result.row.id)
            return {"zoho_id": zoho_id, "created": result.created, "outcome": result.outcome.value,
                    "local_id": result.row.id}
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

    # ── Inbound apply (the heart of the engine) ─────────────────────────────

    async def upsert_payload(
        self, defn: ZohoModuleDefinition, payload: dict, *, source: str
    ) -> tuple[Any, bool]:
        """v1-compatible wrapper: ``(row, created)``."""
        result = await self.apply_payload(defn, payload, source=source)
        return result.row, result.created

    async def apply_payload(
        self, defn: ZohoModuleDefinition, payload: dict, *, source: str, batch: bool = False
    ) -> ApplyResult:
        """Gate, map, resolve nested entities, and write.

        Two storage shapes, one gate. ``contract.crosswalk`` picks between them:

          False (default)  the mirror shape — identity and gate state are
                           columns on the entity row itself. Unchanged.
          True             the crosswalk shape — the entity table holds only
                           business columns; identity, gate state and raw live
                           in ``sync.sync_records``.

        The in-place body below is deliberately left byte-for-byte as it was, so
        "no behaviour change for unconverted modules" is structural rather than
        something a test has to keep proving.
        """
        if defn.config.contract.crosswalk:
            return await self._apply_crosswalk(defn, payload, source=source, batch=batch)
        return await self._apply_in_place(defn, payload, source=source, batch=batch)

    async def _apply_in_place(
        self, defn: ZohoModuleDefinition, payload: dict, *, source: str, batch: bool = False
    ) -> ApplyResult:
        """The mirror path: gate state lives on the entity row (v1 behaviour).

        ``batch=True`` (page apply): the row comes from the page cache and the
        flush is left to the caller; events and hooks are deferred until then.
        """
        cfg = defn.config

        raw_id = extract(payload, cfg.zoho_id_attr)
        if raw_id is MISSING or raw_id in (None, ""):
            raise ValueError(f"payload for '{cfg.module}' lacks id attr '{cfg.zoho_id_attr}'")
        zoho_id = str(raw_id)
        modified = parse_zoho_datetime(payload.get("last_modified_time"))
        digest = payload_hash(payload, cfg.hash_volatile_keys)

        cache_key = (defn.name, zoho_id)
        if batch and self._row_cache is not None and cache_key in self._row_cache:
            row = self._row_cache[cache_key]
        elif batch and self._row_cache is not None and self._row_cache.get(("__loaded__", defn.name)):
            row = None                       # the page preload proved it does not exist
        else:
            row = await self._get_by_zoho_id(defn, zoho_id)
        decision = decide(
            None if row is None else _row_state(row),
            Incoming(modified=modified, payload_hash=digest, source=source),
        )
        if not decision.outcome.writes:
            self._record_event(defn, row, event_type=decision.outcome.value, source=source,
                               zoho_last_modified_time=modified, message=decision.reason)
            return ApplyResult(row, decision.outcome, decision)

        values = map_inbound(cfg, payload)
        values.update(await self._resolve_nested(defn, payload))
        if defn.pre_upsert is not None:
            values = defn.pre_upsert(payload, values) or values

        created = row is None
        before = {} if created else {column: getattr(row, column, None) for column in values}
        changed, diff = build_diff(before, values)
        custom = flatten_custom_fields(payload) if decision.write_raw else None
        raw_changed = decision.write_raw and (created or row.zoho_raw_hash != digest)
        if custom is not None and not created and custom != (row.custom_fields or None):
            changed = sorted({*changed, "custom_fields"})

        outcome = decision.outcome
        if outcome is Outcome.UPDATED and not changed and not raw_changed:
            # The gate could not prove "same" (no version, different payload
            # class), but nothing we store would change: behave as a no-op.
            if modified is not None and modified != row.zoho_last_modified_time:
                row.zoho_last_modified_time = max(filter(None, (modified, row.zoho_last_modified_time)))
            self._record_event(defn, row, event_type=Outcome.UNCHANGED.value, source=source,
                               zoho_last_modified_time=modified, message="no_stored_change")
            return ApplyResult(row, Outcome.UNCHANGED, decision)

        now = datetime.now(UTC)
        if created:
            row = defn.model(zoho_id=zoho_id)
            self.db.add(row)
            if self._row_cache is not None:
                self._row_cache[cache_key] = row      # a duplicate later in the page updates it
        for column, value in values.items():
            setattr(row, column, value)

        if decision.write_raw:
            row.zoho_raw = payload
            row.zoho_raw_hash = digest
            row.zoho_raw_synced_at = now
            row.sync_source = source[:48]
            if custom is not None:
                row.custom_fields = custom
        if modified is not None and (row.zoho_last_modified_time is None or modified > row.zoho_last_modified_time):
            row.zoho_last_modified_time = modified
        if decision.revive:
            row.deleted_at = None
            row.remote_deleted_at = None
        if raw_changed and not changed and not created:
            changed = ["zoho_raw"]            # only unmapped attributes changed

        row.sync_version = (row.sync_version or 0) + 1
        row.synced_at = now
        if hasattr(row, "sync_status") and row.sync_status not in _PUSH_PENDING:
            row.sync_status = SyncStatus.SYNCED.value
            row.sync_error = None
        if hasattr(row, "append_sync_log"):
            row.append_sync_log("inbound_upsert", source=source, outcome=outcome.value)

        if not batch:
            await self.db.flush()
        self._record_event(defn, row, event_type=outcome.value, changed=changed, diff=diff,
                           source=source, zoho_last_modified_time=modified)
        if defn.post_upsert is not None:
            if self._pending_events is not None:
                self._pending_hooks.append((defn.post_upsert, row, payload))
            else:
                await defn.post_upsert(row, payload)
        return ApplyResult(row, outcome, decision)

    # ── Inbound apply, crosswalk shape ──────────────────────────────────────

    async def _apply_crosswalk(
        self, defn: ZohoModuleDefinition, payload: dict, *, source: str, batch: bool = False
    ) -> ApplyResult:
        """The crosswalk path: identity and gate state live in sync.sync_records.

        Order matters. The crosswalk is written BEFORE the entity, because its
        guarded upsert is what fences a stale lane: if another worker applied a
        newer payload between our gate read and this write, the upsert returns
        nothing and we leave the entity alone. Writing the entity first would
        let the loser corrupt business columns before discovering it had lost.
        """
        cfg, contract, model = defn.config, defn.config.contract, defn.model

        raw_id = extract(payload, cfg.zoho_id_attr)
        if raw_id is MISSING or raw_id in (None, ""):
            raise ValueError(f"payload for '{cfg.module}' lacks id attr '{cfg.zoho_id_attr}'")
        external_id = str(raw_id)
        modified = parse_zoho_datetime(payload.get("last_modified_time"))
        digest = payload_hash(payload, cfg.hash_volatile_keys)

        state = await self._crosswalk_state(defn, external_id, batch=batch)
        decision = decide(
            None if state is None else _state_row_state(state),
            Incoming(modified=modified, payload_hash=digest, source=source),
        )
        if not decision.outcome.writes:
            self._record_event(defn, None, event_type=decision.outcome.value, source=source,
                               zoho_last_modified_time=modified, message=decision.reason,
                               zoho_id=external_id)
            return ApplyResult(None, decision.outcome, decision)

        # The anti-corruption boundary: nothing below this line reads the source
        # payload's field names. A thin index row decodes to fewer columns than
        # a detail document, never to NULLs.
        decoded = defn.resolved_translator.decode(payload, shape=PayloadShape.of(source))
        if decoded.warnings:
            logger.warning("zoho.sync.translation_warnings", module=defn.name,
                           external_id=external_id, warnings=decoded.warnings[:10])
        values = decoded.values
        # The identity echo: the module's own Zoho id (currency_id, tax_id,
        # organization_id …) stamped onto the row's zoho_id column. Written
        # here so it can never drift from the crosswalk, which stays the
        # identity of record.
        #
        # Written BEFORE _resolve_entity on purpose: a module may declare the
        # echo column in `match_on` so a row that already carries the source id
        # is ADOPTED rather than duplicated. That is how the seeded company
        # organization becomes the Zoho organization instead of gaining a
        # parallel ZOHO-<id> twin. It stays a match key, never an identity: the
        # crosswalk's unique (tenant, source, module, external_id) is what every
        # subsequent sync resolves on.
        for column in contract.identity_echo:
            values[column] = external_id
        values.update(await self._resolve_nested(defn, payload))
        # Source ids the payload only NAMES (tax_id, currency_id, …) become
        # local foreign keys here, through the crosswalk — one query for the
        # whole page, every referenced module at once. DEFER waiters are queued
        # further down, once the entity has an id for them to wait on.
        reference_plan = await self._resolve_references(defn, payload)
        values.update(reference_plan.values)
        if defn.pre_upsert is not None:
            values = defn.pre_upsert(payload, values) or values

        entity = await self._resolve_entity(defn, state, values)
        created = entity is None
        before = {} if created else {column: getattr(entity, column, None) for column in values}
        changed, diff = build_diff(before, values)

        now = datetime.now(UTC)
        tenant_id = await self._tenant_id()
        xref_values: dict[str, Any] = {
            "entity_table": contract.entity_table or model.__table__.fullname,
            "entity_id": None if created else entity.id,
            "link_state": LinkState.LINKED,
            "synced_at": now,
        }
        # NB: raw_source belongs with the raw document, inside the write_raw
        # branch below. Writing it unconditionally would let a thin list row
        # stamp "list:index" over a stored detail document — the provenance
        # rank would then say the row is thin, and the next thin payload would
        # be allowed to overwrite the rich one it should never touch.
        # Only ever WIDEN the crosswalk's organization: passing None on every
        # apply would clobber a good value. A created entity's org is stamped by
        # the link step, once its row exists.
        if not created and getattr(entity, "organization_id", None) is not None:
            xref_values["organization_id"] = entity.organization_id
        # An undated payload must not erase the stored fence, so the column is
        # omitted rather than set to NULL; the SQL guard reads a missing
        # EXCLUDED value as "always allowed", which is the rule for the
        # undated modules (Zoho settings endpoints) the gate hashes instead.
        if modified is not None:
            xref_values["source_modified_at"] = modified
        if decision.write_raw:
            xref_values |= {"raw": payload, "raw_hash": digest, "raw_synced_at": now,
                            "raw_source": source[:48]}
            if contract.capture_custom_fields:
                xref_values["custom_fields"] = flatten_custom_fields(payload)
            if contract.capture_comments and isinstance(payload.get("comments"), list | dict):
                xref_values["comments"] = {"items": payload["comments"]}
        if decision.revive:
            xref_values["remote_deleted_at"] = None

        # no_autoflush matters more than it looks: this is a Core statement in
        # the middle of a batched page, and an autoflush here would push the
        # page's pending entity INSERTs out one record at a time, silently
        # turning SQLAlchemy's insertmanyvalues into N round trips. The upsert
        # never needs pending entity state — entity_id is passed explicitly, or
        # NULL and patched after the flush — so suppressing it is safe.
        with self.db.no_autoflush:
            written = await upsert_record(
                self.db, tenant_id=tenant_id, source_system=contract.source_system,
                module=defn.name, external_id=external_id, values=xref_values,
            )
        if written is None:
            # Another lane applied a newer payload between the gate read and
            # here. Nothing was written, and the entity is untouched.
            logger.info("zoho.sync.crosswalk_lost_race", module=defn.name, external_id=external_id)
            self._record_event(defn, None, event_type=Outcome.STALE_IGNORED.value, source=source,
                               zoho_last_modified_time=modified, message="lost_upsert_race",
                               zoho_id=external_id)
            return ApplyResult(entity, Outcome.STALE_IGNORED,
                               Decision(Outcome.STALE_IGNORED, reason="lost_upsert_race"))

        xref_id, sync_version = written
        if created:
            entity = model()
            self.db.add(entity)
        for column, value in values.items():
            setattr(entity, column, value)
        if decision.revive and getattr(entity, "deleted_at", None) is not None:
            # Only a SYNC tombstone gets revived here; a purely local delete
            # never reaches this branch (the gate returns UPDATED, not
            # RESURRECTED, when remote_deleted_at is NULL).
            entity.deleted_at = None

        history = SyncPayload(
            tenant_id=tenant_id,
            organization_id=getattr(entity, "organization_id", None),
            sync_record_id=xref_id,
            source_system=contract.source_system,
            module=defn.name,
            external_id=external_id,
            entity_table=xref_values["entity_table"],
            entity_id=None if created else entity.id,
            outcome=decision.outcome.value,
            raw=payload if contract.history_raw else None,
            raw_hash=digest,
            raw_source=source[:48],
            sync_version=sync_version,
            changed_fields=changed or None,
            run_id=self.run_id,
        )
        self.db.add(history)

        if created:
            # entity.id exists only after the flush; the crosswalk and the
            # history row are linked to it then (see _run_deferred).
            self._pending_links.append((xref_id, contract.source_system, entity, history))

        if not batch:
            await self.db.flush()
            await self._link_pending()

        # DEFER waiters are recorded against the entity, not the payload: the
        # queue row names the row that is waiting, and only now do we have it.
        for rule, missing_id in reference_plan.defer:
            self._pending_reference_writes.append((defn, entity, rule, missing_id))

        self._record_event(defn, entity, event_type=decision.outcome.value, changed=changed,
                           diff=diff, source=source, zoho_last_modified_time=modified,
                           zoho_id=external_id)
        if defn.post_upsert is not None:
            if self._pending_events is not None:
                self._pending_hooks.append((defn.post_upsert, entity, payload))
            else:
                await defn.post_upsert(entity, payload)
        return ApplyResult(entity, decision.outcome, decision)

    # ── Reference resolution (redesign §4) ──────────────────────────────────

    async def _preload_references(
        self, defn: ZohoModuleDefinition, payloads: list[dict]
    ) -> None:
        """Resolve every reference the PAGE names, in one query.

        This is the payoff the crosswalk was built for: a page of documents
        naming taxes, currencies, contacts and items resolves all four modules
        together, instead of one query per module against a per-table
        ``zoho_id`` column. The cache survives the page, so the same twelve
        taxes an invoice page repeats are resolved once.
        """
        rules = defn.config.contract.references
        if not rules:
            self._reference_cache = None
            return
        pairs = pairs_in_page(rules, payloads)
        self._reference_cache = await self._resolve_pairs(pairs)

    async def _resolve_pairs(self, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int | None]:
        if not pairs:
            return {}
        rows = await self.db.execute(resolve_many(
            tenant_id=await self._tenant_id(), source_system="zoho", pairs=pairs,
        ))
        resolved: dict[tuple[str, str], int | None] = dict.fromkeys(pairs)
        for module, external_id, _entity_table, entity_id, _link_state in rows:
            resolved[(module, external_id)] = entity_id
        return resolved

    async def _resolve_references(self, defn: ZohoModuleDefinition, payload: dict) -> Plan:
        """Turn this record's source ids into local foreign keys.

        Policy (which misses fetch, stub, defer or are ignored, and when the
        budget says no) is pure and lives in ``app/modules/sync/references.py``.
        Everything here is the mechanism that policy asks for.
        """
        rules = defn.config.contract.references
        if not rules:
            return Plan()

        cache = self._reference_cache
        if cache is None:                      # single-record apply: resolve just this one
            cache = await self._resolve_pairs(pairs_in_page(rules, [payload]))

        if self._reference_budget is None:
            self._reference_budget = Budget(limit=defn.config.max_reference_fetches_per_run)
        plan = plan_references(rules, payload, cache, budget=self._reference_budget)

        # FETCH: go get the master now. Single-flight per run — a page of 200
        # invoices naming one missing tax fetches it once, not 200 times.
        for module, external_id in plan.fetch:
            if (module, external_id) in self._reference_attempted:
                continue
            self._reference_attempted.add((module, external_id))
            if await self._fetch_reference(module, external_id):
                cache.update(await self._resolve_pairs([(module, external_id)]))

        # STUB: a provisional row linked NOW, so the document is correct and
        # queryable immediately. Idempotent — the owning module's real sync
        # finds the crosswalk row and fills the same entity, never a duplicate.
        for module, external_id in plan.stub:
            entity_id = await self._stub_reference(module, external_id)
            if entity_id is not None:
                cache[(module, external_id)] = entity_id

        # Re-plan against what fetching and stubbing just resolved: pure, cheap,
        # and the step that actually turns a FETCH/STUB into a foreign key.
        if plan.fetch or plan.stub:
            plan = plan_references(rules, payload, cache, budget=self._reference_budget)
        return plan

    async def _stub_reference(self, module: str, external_id: str) -> int | None:
        """A minimal provisional row for a master we have not synced yet.

        One INSERT against a quota-free local table, versus one API call against
        a budget the whole fleet shares — which is why this, not FETCH, is the
        default for high-cardinality references (redesign §4.2).
        """
        try:
            owner = await self.resolve(module)
        except KeyError:
            logger.warning("sync.reference.unknown_module", module=module)
            return None
        contract = owner.config.contract
        if not contract.crosswalk:
            # An in-place mirror has no crosswalk row to fill later, so a stub
            # here would become a permanent orphan rather than a placeholder.
            logger.info("sync.reference.stub_skipped", module=module,
                        reason="module is not on the crosswalk")
            return None

        tenant_id = await self._tenant_id()
        entity = owner.model()
        for column in contract.identity_echo:
            setattr(entity, column, external_id)
        if "status" in owner.model.__table__.c:
            entity.status = "provisional"
        self.db.add(entity)
        await self.db.flush()

        await upsert_record(
            self.db, tenant_id=tenant_id, source_system=contract.source_system,
            module=module, external_id=external_id,
            values={
                "entity_table": contract.entity_table or owner.model.__table__.fullname,
                "entity_id": entity.id,
                "link_state": LinkState.PROVISIONAL,
                "organization_id": getattr(entity, "organization_id", None),
                "synced_at": datetime.now(UTC),
            },
        )
        logger.info("sync.reference.stubbed", module=module, external_id=external_id,
                    entity_id=entity.id)
        return entity.id

    async def _fetch_reference(self, module: str, external_id: str) -> bool:
        """Fetch one referenced master through the normal transport and apply it.

        Through ``self.client``, so the governor, the breaker and the rate
        budget all still apply — an unplanned reference fetch is not a licence
        to bypass them. A miss is logged and never raised: a document must not
        fail because a master it names has been deleted upstream.
        """
        try:
            owner = await self.resolve(module)
        except KeyError:
            logger.warning("sync.reference.unknown_module", module=module)
            return False
        try:
            response = await self.client.get(owner.config.detail_path(external_id), **_api_kw(owner.config))
            if not isinstance(response.data, dict):
                return False
            async with self.db.begin_nested():
                await self.apply_payload(owner, response.data, source="reference_fetch")
            logger.info("sync.reference.fetched", module=module, external_id=external_id)
            return True
        except ZohoNotFoundError:
            logger.warning("sync.reference.gone_upstream", module=module, external_id=external_id)
            return False
        except ZohoApiError:
            raise                              # quota / breaker — the runner decides
        except Exception as exc:               # noqa: BLE001 — one reference never sinks a page
            logger.warning("sync.reference.fetch_failed", module=module,
                           external_id=external_id, error=str(exc)[:200])
            return False

    async def _flush_pending_references(self) -> None:
        """Queue DEFER waiters, now that every entity in the page has an id.

        Deliberately after the flush: a ``PendingReference`` records *which row*
        is waiting for what, and a row inserted this page has no id until then.
        The reconcile lane drains the queue — this is also the honest answer to
        "what did we fail to link?", a number an operator can watch instead of
        silent NULLs.
        """
        waiting, self._pending_reference_writes = self._pending_reference_writes, []
        if not waiting:
            return
        tenant_id = await self._tenant_id()
        for defn, entity, rule, external_id in waiting:
            entity_id = getattr(entity, "id", None)
            if entity_id is None:                      # the flush failed for this row
                continue
            table = defn.config.contract.entity_table or defn.model.__table__.fullname
            await self.db.execute(
                pg_insert(PendingReference).values(
                    tenant_id=tenant_id,
                    organization_id=getattr(entity, "organization_id", None),
                    source_system=defn.config.contract.source_system,
                    module=rule.module,
                    external_id=external_id,
                    waiting_table=table,
                    waiting_id=entity_id,
                    waiting_column=rule.fk,
                ).on_conflict_do_nothing(constraint="uq_pending_references_waiter")
            )

    async def _resolve_entity(
        self, defn: ZohoModuleDefinition, state: _CrosswalkState | None, values: dict[str, Any]
    ) -> Any | None:
        """Which local row this payload belongs to: the linked one, a business-key
        match, or none yet (docs/implementation-plan/sync-crosswalk-redesign.md §2.5)."""
        model = defn.model
        if state is not None and state.entity_id is not None:
            entity = await self.db.scalar(
                select(model).where(model.id == state.entity_id)
                .execution_options(include_deleted=True).limit(1)
            )
            if entity is not None:
                return entity
            logger.warning("zoho.sync.crosswalk_orphan", module=defn.name,
                           entity_id=state.entity_id)

        match_on = defn.config.contract.match_on
        if not match_on:
            return None
        # A match key with a missing value is not a match — never fall back to
        # "any row with NULL there", which would merge unrelated records.
        criteria = []
        for column in match_on:
            value = values.get(column)
            if value is None:
                return None
            criteria.append(getattr(model, column) == value)
        return await self.db.scalar(
            select(model).where(*criteria).execution_options(include_deleted=True).limit(1)
        )

    async def _crosswalk_state(
        self, defn: ZohoModuleDefinition, external_id: str, *, batch: bool
    ) -> _CrosswalkState | None:
        key = (defn.name, external_id)
        if batch and self._state_cache is not None:
            if key in self._state_cache:
                return self._state_cache[key]
            if defn.name in self._state_loaded:
                return None                  # the page preload proved it does not exist
        states = await self._load_crosswalk_states(defn, [external_id])
        return states.get(key)

    async def _load_crosswalk_states(
        self, defn: ZohoModuleDefinition, external_ids: list[str]
    ) -> dict[tuple[str, str], _CrosswalkState]:
        """Gate state for a set of records in ONE query, entity join included."""
        if not external_ids:
            return {}
        rows = (await self.db.execute(crosswalk_load_page(
            tenant_id=await self._tenant_id(),
            source_system=defn.config.contract.source_system,
            module=defn.name,
            external_ids=external_ids,
            entity_model=defn.model,
        ))).all()
        return {
            (defn.name, row._mapping["external_id"]): _CrosswalkState.of(row._mapping)
            for row in rows
        }

    async def _tenant_id(self) -> int:
        """The tenant every crosswalk write is scoped to.

        The crosswalk is written with Core statements, which the ORM's flush
        stamping never sees — which is exactly what ``write_tenant_id`` exists
        for (context tenant, else the default tenant).
        """
        return await write_tenant_id(self.db)

    async def _link_pending(self) -> None:
        """Stamp entity ids onto the crosswalk and history rows created this page.

        A new entity has no id until the flush, so its crosswalk row is inserted
        with ``entity_id IS NULL`` and patched here. The patch also carries the
        organization across, which is why the upsert never passes one.
        """
        links, self._pending_links = self._pending_links, []
        for xref_id, source_system, entity, history in links:
            entity_id = getattr(entity, "id", None)
            if entity_id is None:                      # the flush failed for this row
                continue
            if history is not None:
                history.entity_id = entity_id
            await self.db.execute(
                update(SyncRecord)
                .where(SyncRecord.id == xref_id, SyncRecord.source_system == source_system)
                .values(entity_id=entity_id,
                        organization_id=getattr(entity, "organization_id", None))
            )

    def _record_event(
        self,
        defn: ZohoModuleDefinition,
        row: Any,
        *,
        event_type: str,
        changed: list[str] | None = None,
        diff: dict | None = None,
        source: str | None = None,
        zoho_last_modified_time: datetime | None = None,
        message: str | None = None,
        zoho_id: str | None = None,
    ) -> None:
        """Append a record-level sync event to the CURRENT transaction.

        Added to the session rather than written separately, so the event
        exists exactly when the change commits (docs/zoho-sync-implementation/
        sync-events.md).

        ``zoho_id`` is passed explicitly by the crosswalk path, where the
        external id lives on the crosswalk row rather than on the entity.
        """
        if not events_enabled_for(event_type):
            return
        fields = dict(event_type=event_type, source=source, changed=changed, diff=diff,
                      zoho_last_modified_time=zoho_last_modified_time, message=message,
                      zoho_id=zoho_id)
        if self._pending_events is not None:
            self._pending_events.append((defn, row, fields))   # row ids exist after the page flush
            return
        self._add_event(defn, row, **fields)

    def _add_event(self, defn: ZohoModuleDefinition, row: Any, *, event_type: str, source: str | None,
                   changed: list[str] | None, diff: dict | None,
                   zoho_last_modified_time: datetime | None, message: str | None,
                   zoho_id: str | None = None) -> None:
        self.db.add(
            new_sync_event(
                module=defn.name, event_type=event_type, direction="pull", source=source,
                local_id=getattr(row, "id", None),
                zoho_id=zoho_id if zoho_id is not None else getattr(row, "zoho_id", None),
                run_id=self.run_id, changed_fields=changed or None, diff=diff or None,
                zoho_last_modified_time=zoho_last_modified_time, message=message,
            )
        )

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
                    result = await self.apply_payload(child_defn, child_payload,
                                                      source=f"nested:{defn.name}", batch=False)
                    last_child = result.row
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
        self,
        defn: ZohoModuleDefinition,
        mode: SyncStrategyName,
        report: SyncRunReport,
        *,
        started: float,
        page_hook: PageHook | None,
    ) -> None:
        cfg = defn.config
        params: dict[str, Any] = dict(cfg.list_params)
        max_modified: datetime | None = None
        seen_zoho_ids: set[str] = set()
        # The watermark may advance page by page only when Zoho returns rows
        # oldest-first; otherwise it moves once, when the scan completes.
        sorted_watermark = mode is SyncStrategyName.INCREMENTAL and bool(cfg.sort_column)
        start_page = report.start_page
        if sorted_watermark:
            start_page = 1           # the advanced watermark IS the resume point

        if mode is SyncStrategyName.INCREMENTAL:
            cursor = await self._get_cursor(defn)
            if cursor:
                params[cfg.modified_since_param] = cursor
            if cfg.sort_column:
                params.update(sort_column=cfg.sort_column, sort_order="A")

        page_number = start_page
        async for page in self._pages(cfg, params, start_page):
            report.pages += 1
            records = page.data if isinstance(page.data, list) else ([page.data] if page.data else [])
            ids = [_zoho_id_of(record, cfg.zoho_id_attr) for record in records]
            stored = await self._stored_versions(defn, [i for i in ids if i]) if cfg.detail_required else {}

            # Phase 1 — materialise: detail fetch / skip / queue, per-record isolation.
            to_apply: list[tuple[str | None, dict, str]] = []
            for record, zoho_id in zip(records, ids, strict=True):
                report.listed += 1
                if zoho_id:
                    seen_zoho_ids.add(zoho_id)
                modified = parse_zoho_datetime(record.get("last_modified_time"))
                if modified and (max_modified is None or modified > max_modified):
                    max_modified = modified
                try:
                    item = await self._materialise(defn, mode, record, zoho_id, report, stored.get(zoho_id))
                except ZohoNotFoundError:
                    report.skipped += 1
                    continue
                except ZohoApiError:
                    raise  # upstream failure — abort, let the runner decide
                except Exception as e:  # one bad record never sinks the run
                    await self._record_failure(defn, zoho_id, e, report)
                    continue
                if item is not None:
                    to_apply.append(item)

            # Phase 2 — apply the page: one preload query, one flush.
            await self._apply_page(defn, to_apply, report)
            # Phase 3 — index_then_detail: the rows now exist; fill them in.
            await self._apply_detail_backlog(defn, report)

            context = page.page_context
            page_number = (context.page if context and context.page else page_number)
            has_more = bool(context and context.has_more_page)
            if sorted_watermark and max_modified is not None:
                report.cursor = max_modified.strftime(_CURSOR_FMT)
                await self._save_cursor(defn, report.cursor)

            stop = _budget_hit(cfg, report, started) if has_more else None
            if stop:
                report.stop_reason = stop
                report.next_page = 1 if sorted_watermark else page_number + 1
            if page_hook is not None:
                await page_hook(report, report.next_page or (page_number + 1 if has_more else 1))
            if stop:
                logger.info("zoho.sync.slice_yielded", module=defn.name, reason=stop,
                            next_page=report.next_page, pages=report.pages)
                return
            page_number += 1

        if max_modified is not None:
            report.cursor = max_modified.strftime(_CURSOR_FMT)

        # Reconciliation: only a scan that saw EVERY page in this slice may
        # conclude that a missing row was deleted upstream.
        if mode is SyncStrategyName.FULL and cfg.soft_delete_missing and seen_zoho_ids:
            if report.start_page == 1:
                report.soft_deleted = await self._soft_delete_missing(defn, seen_zoho_ids)
            else:
                logger.info("zoho.sync.soft_delete_missing_skipped", module=defn.name,
                            reason="multi_slice_scan", start_page=report.start_page)

    async def _pages(self, cfg, params: dict[str, Any], start_page: int):
        """List pages — paginated endpoints, or one response for the few list
        endpoints Zoho serves without ``page_context`` (``paginated=False``)."""
        if not cfg.paginated:
            yield await self.client.get(cfg.endpoint, params=params or None, **_api_kw(cfg))
            return
        async for page in self.client.paginate(
            cfg.endpoint, params=params, per_page=cfg.batch_size, start_page=start_page, **_api_kw(cfg)
        ):
            yield page

    async def _record_failure(self, defn: ZohoModuleDefinition, zoho_id: str | None, error: Exception,
                              report: SyncRunReport) -> None:
        # A record whose index apply failed does not get a detail call: the
        # fetch would cost quota to produce a second failure for the same row,
        # and the run's error count would double-report it.
        if zoho_id and zoho_id in self._detail_backlog:
            self._detail_backlog.remove(zoho_id)
        report.errors += 1
        logger.error("zoho_record_sync_failed", module=defn.name, zoho_id=zoho_id, error=str(error))
        await record_queue_log(
            self.db, module=defn.name, operation="inbound_upsert",
            status="failed", zoho_id=zoho_id, error=str(error)[:2000],
        )

    async def _apply_page(
        self, defn: ZohoModuleDefinition, items: list[tuple[str | None, dict, str]], report: SyncRunReport
    ) -> None:
        """Apply one page: preload rows (1 query), gate + write all, flush once.

        On a database error the page's savepoint is rolled back and the page is
        re-applied record by record (each in its own savepoint), so the bad
        record is isolated and counted — exactly v1's per-record semantics.
        """
        if not items:
            return
        if defn.config.contract.crosswalk:
            # A second payload for an id already in THIS page cannot see the row
            # the first one is about to insert (the preload predates it), so it
            # would insert a duplicate entity behind the one crosswalk row. The
            # zoho_id echo's unique index used to catch that by accident; a
            # module without the echo has no such net, so repeats wait for the
            # first flush and are applied as updates against a fresh preload.
            seen: set[str] = set()
            first: list[tuple[str | None, dict, str]] = []
            repeats: list[tuple[str | None, dict, str]] = []
            for item in items:
                (repeats if item[0] and item[0] in seen else first).append(item)
                if item[0]:
                    seen.add(item[0])
            if repeats:
                await self._apply_page(defn, first, report)
                await self._apply_page(defn, repeats, report)
                return
        outcomes: list[tuple[str | None, Outcome]] = []
        failures: list[tuple[str | None, Exception]] = []
        ids = [zid for zid, _, _ in items if zid]
        if defn.config.contract.crosswalk:
            self._row_cache = {}
            self._state_cache = await self._load_crosswalk_states(defn, ids)
            self._state_loaded.add(defn.name)
            await self._preload_references(defn, [payload for _, payload, _ in items])
        else:
            self._row_cache = await self._load_rows(defn, ids)
        self._pending_events, self._pending_hooks = [], []
        try:
            async with self.db.begin_nested():
                for zoho_id, payload, source in items:
                    try:
                        result = await self.apply_payload(defn, payload, source=source, batch=True)
                    except (ZohoApiError, SQLAlchemyError):
                        raise
                    except Exception as e:  # mapping/validation error: this record only
                        failures.append((zoho_id, e))
                        continue
                    outcomes.append((zoho_id, result.outcome))
                await self.db.flush()
            await self._run_deferred()
        except SQLAlchemyError as exc:
            logger.warning("zoho.sync.page_batch_failed", module=defn.name, records=len(items),
                           error=str(exc)[:300])
            self._reset_batch()
            await self._apply_one_by_one(defn, items, report)
            return
        finally:
            self._reset_batch()

        for zoho_id, error in failures:
            await self._record_failure(defn, zoho_id, error, report)
        for zoho_id, outcome in outcomes:
            _count(report, outcome)
            if zoho_id:
                await self._touch_last_id(defn, zoho_id)

    async def _apply_detail_backlog(self, defn: ZohoModuleDefinition, report: SyncRunReport) -> None:
        """Phase two of ``index_then_detail``: fetch each listed record's full
        document and upsert it over the row the index already created.

        Zoho's list endpoints are thin by design — a tax, an invoice or an
        organization carries only a summary there — so the detail document is
        where most columns actually come from. Running it as a second apply
        rather than a pre-fetch means a failure here costs the *detail*, not
        the record: the row is already in place, correct as far as the index
        went, and the next run completes it.

        The apply gate does the rest: ``detail_fetch`` outranks ``list:*``, so
        the richer payload wins and the raw document it stores is the full one.
        """
        backlog, self._detail_backlog = self._detail_backlog, []
        if not backlog:
            return
        cfg = defn.config
        for external_id in backlog:
            if cfg.detail_dispatch == "queued":
                log = await record_queue_log(
                    self.db, module=defn.name, operation="detail_fetch",
                    status="queued", zoho_id=external_id,
                )
                from app.tasks.zoho_sync import fetch_detail  # lazy: tasks import this module

                log.celery_task_id = fetch_detail.delay(defn.name, external_id, queue_log_id=log.id).id
                report.queued_details += 1
                continue
            try:
                if cfg.wait_between_calls:
                    await asyncio.sleep(cfg.wait_between_calls)
                response = await self.client.get(cfg.detail_path(external_id), **_api_kw(cfg))
                if not isinstance(response.data, dict):
                    continue
                async with self.db.begin_nested():
                    result = await self.apply_payload(defn, response.data, source="detail_fetch")
                _count(report, result.outcome)
            except ZohoNotFoundError:
                # Deleted upstream between the listing and the detail fetch.
                report.skipped += 1
                logger.warning("zoho_detail_gone", module=defn.name, zoho_id=external_id)
            except ZohoApiError:
                raise                      # upstream failure — the runner decides
            except Exception as e:  # one bad detail never sinks the run
                await self._record_failure(defn, external_id, e, report)

    async def _apply_one_by_one(
        self, defn: ZohoModuleDefinition, items: list[tuple[str | None, dict, str]], report: SyncRunReport
    ) -> None:
        """Fallback after a failed batch: v1 semantics, one savepoint per record.

        A unique violation on insert means another lane inserted the same
        record a moment ago — re-read and apply once more as an update.
        """
        for zoho_id, payload, source in items:
            for attempt in (1, 2):
                try:
                    async with self.db.begin_nested():
                        result = await self.apply_payload(defn, payload, source=source)
                    _count(report, result.outcome)
                    if zoho_id:
                        await self._touch_last_id(defn, zoho_id)
                    break
                except ZohoApiError:
                    raise
                except Exception as e:
                    if attempt == 1 and isinstance(e, SQLAlchemyError) and "unique" in str(e).lower():
                        continue
                    await self._record_failure(defn, zoho_id, e, report)
                    break

    async def _run_deferred(self) -> None:
        # Links first: events, hooks and reference waiters all want a row that
        # knows its id.
        await self._link_pending()
        await self._flush_pending_references()
        events, hooks = self._pending_events or [], self._pending_hooks
        self._pending_events, self._pending_hooks = None, []
        for defn, row, fields in events:
            self._add_event(defn, row, **fields)
        for hook, row, payload in hooks:
            await hook(row, payload)

    def _reset_batch(self) -> None:
        self._row_cache = None
        self._pending_events, self._pending_hooks = None, []
        self._state_cache, self._state_loaded = None, set()
        self._pending_links = []
        # Per-page only. The budget and the single-flight set live for the run.
        self._reference_cache = None
        self._pending_reference_writes = []

    async def _load_rows(self, defn: ZohoModuleDefinition, ids: list[str]) -> dict[tuple[str, str], Any]:
        """Every stored row of the page in ONE query (live rows win over ghosts)."""
        cache: dict[tuple[str, str], Any] = {("__loaded__", defn.name): True}
        if not ids:
            return cache
        model = defn.model
        rows = (await self.db.scalars(
            select(model).where(model.zoho_id.in_(sorted(set(ids))))
            .execution_options(include_deleted=True)
            .order_by(model.deleted_at.is_not(None).desc())      # ghosts first, live rows overwrite
        )).all()
        for row in rows:
            cache[(defn.name, row.zoho_id)] = row
        return cache

    async def _materialise(
        self,
        defn: ZohoModuleDefinition,
        mode: SyncStrategyName,
        record: dict,
        zoho_id: str | None,
        report: SyncRunReport,
        stored: _StoredVersion | None = None,
    ) -> tuple[str | None, dict, str] | None:
        """Turn a listed record into the payload to apply, or None (skipped/queued)."""
        cfg = defn.config
        needs_detail = cfg.detail_required and mode is not SyncStrategyName.INDEX

        if needs_detail and zoho_id and stored is not None and _already_current(stored, record):
            # The row already holds the detail document of this exact version:
            # the detail call would only confirm it. Spend nothing.
            report.unchanged += 1
            report.details_saved += 1
            return None

        if needs_detail and zoho_id and cfg.index_then_detail:
            # Phase one: apply the listed row now so the record exists. Phase
            # two runs after the page is written (_apply_detail_backlog).
            self._detail_backlog.append(zoho_id)
            return zoho_id, record, f"list:{mode.value}"

        if needs_detail and zoho_id and cfg.detail_dispatch == "queued":
            # Fan out: journal first, then one Celery task per record.
            log = await record_queue_log(
                self.db, module=defn.name, operation="detail_fetch", status="queued", zoho_id=zoho_id
            )
            from app.tasks.zoho_sync import fetch_detail  # lazy: tasks import this module

            async_result = fetch_detail.delay(defn.name, zoho_id, queue_log_id=log.id)
            log.celery_task_id = async_result.id
            report.queued_details += 1
            return None

        source = f"list:{mode.value}"
        if needs_detail and zoho_id:
            # Inline N+1: fetch the full record now, pace with wait_between_calls.
            if cfg.wait_between_calls:
                await asyncio.sleep(cfg.wait_between_calls)
            response = await self.client.get(cfg.detail_path(zoho_id), **_api_kw(cfg))
            if isinstance(response.data, dict):
                record, source = response.data, "detail_fetch"
        return zoho_id, record, source

    async def _soft_delete_missing(self, defn: ZohoModuleDefinition, seen: set[str]) -> int:
        """Tombstone local rows whose zoho_id no longer exists upstream — guarded.

        Three safeguards (docs/zoho-sync-implementation/control-plane.md §6):
          1. off unless ``ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`` — one list scan
             is not evidence of deletion (Zoho's item list omits inactive items);
          2. the missing set is computed in Python from the live ids — never a
             ``NOT IN`` with every seen id (asyncpg caps bind params at 32,767);
          3. a mass-delete guard refuses when more than
             ``max(ZOHO_SYNC_MASS_DELETE_MIN, ZOHO_SYNC_MASS_DELETE_PCT × live)``
             rows would go — that shape is a partial scan, not a real purge.

        ``remote_deleted_at`` records the evidence time, so a later payload
        that is not newer than it cannot revive the row (apply gate rule 2).
        """
        from app.core.conf import settings

        if not settings.ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING:
            logger.warning(
                "zoho.sync.soft_delete_missing_skipped",
                module=defn.name, reason="disabled_by_setting", seen=len(seen),
            )
            return 0

        model = defn.model
        crosswalk = defn.config.contract.crosswalk
        if crosswalk:
            live_ids = set((await self.db.scalars(crosswalk_live_ids(
                tenant_id=await self._tenant_id(),
                source_system=defn.config.contract.source_system,
                module=defn.name,
            ))).all())
        else:
            live_ids = set(
                (await self.db.scalars(select(model.zoho_id).where(model.zoho_id.is_not(None)))).all()
            )
        missing = sorted(live_ids - seen)
        if not missing:
            return 0

        limit = max(settings.ZOHO_SYNC_MASS_DELETE_MIN, int(len(live_ids) * settings.ZOHO_SYNC_MASS_DELETE_PCT))
        if len(missing) > limit:
            logger.critical(
                "zoho.sync.mass_delete_guard",
                module=defn.name, missing=len(missing), live=len(live_ids), limit=limit,
            )
            return 0

        if crosswalk:
            return await self._tombstone_crosswalk(defn, missing)

        now = datetime.now(UTC)
        deleted = 0
        for start in range(0, len(missing), 1000):
            chunk = missing[start:start + 1000]
            rows = (await self.db.scalars(select(model).where(model.zoho_id.in_(chunk)))).all()
            for row in rows:
                row.deleted_at = now
                row.remote_deleted_at = now
                row.sync_version = (row.sync_version or 0) + 1
                if hasattr(row, "sync_status"):
                    row.sync_status = SyncStatus.DELETED.value
                if hasattr(row, "append_sync_log"):
                    row.append_sync_log("soft_deleted_missing_upstream")
                self._record_event(defn, row, event_type="tombstoned", changed=["deleted_at"],
                                   diff={"deleted_at": [None, now.isoformat()]})
                deleted += 1
        await self.db.flush()
        return deleted

    async def _tombstone_crosswalk(self, defn: ZohoModuleDefinition, missing: list[str]) -> int:
        """Tombstone records the source stopped listing — BOTH sides, one transaction.

        The evidence is split by design: ``remote_deleted_at`` on the crosswalk
        says "the source deleted it" and fences resurrection; ``deleted_at`` on
        the entity is what the rest of the application sees. Writing only one of
        them leaves a half-tombstone the gate cannot reason about, so they are
        written together or not at all (redesign plan §2.7).
        """
        now = datetime.now(UTC)
        tenant_id = await self._tenant_id()
        source_system = defn.config.contract.source_system
        deleted = 0
        for start in range(0, len(missing), 1000):
            chunk = missing[start:start + 1000]
            states = await self._load_crosswalk_states(defn, chunk)
            entity_ids = [s.entity_id for s in states.values() if s.entity_id is not None]
            if entity_ids:
                rows = (await self.db.scalars(
                    select(defn.model).where(defn.model.id.in_(entity_ids))
                    .execution_options(include_deleted=True)
                )).all()
                for row in rows:
                    if row.deleted_at is None:
                        row.deleted_at = now
                    self._record_event(defn, row, event_type="tombstoned", changed=["deleted_at"],
                                       diff={"deleted_at": [None, now.isoformat()]})
            await self.db.execute(crosswalk_tombstone(
                tenant_id=tenant_id, source_system=source_system, module=defn.name,
                external_ids=chunk, at=now,
            ))
            deleted += len(chunk)
        await self.db.flush()
        return deleted

    # ── Lookups & stats ─────────────────────────────────────────────────────

    async def _get_by_zoho_id(self, defn: ZohoModuleDefinition, zoho_id: str) -> Any | None:
        stmt = (
            select(defn.model)
            .where(defn.model.zoho_id == zoho_id)
            .execution_options(include_deleted=True)  # revive soft-deleted rows on re-sync
            .order_by(defn.model.deleted_at.is_not(None))  # a live row wins over a ghost
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def _stored_versions(self, defn: ZohoModuleDefinition, ids: list[str]) -> dict[str, _StoredVersion]:
        """One query per page: the stored version of every listed record."""
        if not ids:
            return {}
        if defn.config.contract.crosswalk:
            states = await self._load_crosswalk_states(defn, ids)
            return {
                external_id: _StoredVersion(
                    state.source_modified_at, state.raw_source,
                    state.remote_deleted_at is not None or state.entity_deleted_at is not None,
                )
                for (_, external_id), state in states.items()
            }
        model = defn.model
        rows = await self.db.execute(
            select(model.zoho_id, model.zoho_last_modified_time, model.sync_source,
                   model.remote_deleted_at, model.deleted_at)
            .where(model.zoho_id.in_(ids))
            .execution_options(include_deleted=True)
        )
        return {
            zoho_id: _StoredVersion(modified, source, remote_deleted is not None or deleted is not None)
            for zoho_id, modified, source, remote_deleted, deleted in rows
        }

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

    async def _save_cursor(self, defn: ZohoModuleDefinition, cursor: str) -> None:
        """Advance the incremental watermark with the page (same transaction)."""
        stat = await self._get_stat(defn.name)
        stat.last_incremental_cursor = cursor
        await self.db.flush()

    async def _touch_last_id(self, defn: ZohoModuleDefinition, zoho_id: str) -> None:
        # Cheap in-memory update; persisted with the final stats upsert.
        self._last_zoho_id = zoho_id  # noqa: SLF001 — engine-local scratch

    async def _update_stats(self, defn: ZohoModuleDefinition, report: SyncRunReport, error: str | None = None) -> None:
        try:
            stat = await self._get_stat(defn.name)
            now = datetime.now(UTC)
            stat.last_sync_time = now
            if report.mode == SyncStrategyName.FULL.value and report.next_page is None and not error:
                stat.last_full_sync_time = now
            if report.cursor:
                stat.last_incremental_cursor = report.cursor
            if getattr(self, "_last_zoho_id", None):
                stat.last_zoho_id_synced = self._last_zoho_id
            stat.total_records_synced = (stat.total_records_synced or 0) + report.created + report.updated
            stat.records_created = (stat.records_created or 0) + report.created
            stat.records_updated = (stat.records_updated or 0) + report.updated + report.resurrected
            stat.skipped_records = (
                (stat.skipped_records or 0) + report.skipped + report.unchanged + report.stale_ignored
            )
            stat.error_count = (stat.error_count or 0) + report.errors + (1 if error else 0)
            stat.run_count = (stat.run_count or 0) + 1
            stat.last_run_status = "failed" if error else report.status
            stat.last_run_mode = report.mode
            stat.last_run_duration_ms = report.duration_ms
            stat.last_error = error
            await self.db.flush()
        except Exception:  # stats must never mask the real failure
            logger.error("zoho_sync_stats_update_failed", module=defn.name, exc_info=True)


# ── helpers ─────────────────────────────────────────────────────────────────

_COUNTER = {
    Outcome.INSERTED: "created",
    Outcome.UPDATED: "updated",
    Outcome.RESURRECTED: "resurrected",
    Outcome.UNCHANGED: "unchanged",
    Outcome.STALE_IGNORED: "stale_ignored",
}


def _count(report: SyncRunReport, outcome: Outcome) -> None:
    counter = _COUNTER[outcome]
    setattr(report, counter, getattr(report, counter) + 1)


def _api_kw(cfg) -> dict[str, Any]:
    """Route Inventory modules to the Inventory base URL (Books is the default)."""
    return {"api": cfg.api} if cfg.api != "books" else {}


def _zoho_id_of(record: dict, attr: str) -> str | None:
    raw_id = extract(record, attr)
    return str(raw_id) if raw_id not in (MISSING, None, "") else None


def _row_state(row: Any) -> RowState:
    return RowState(
        zoho_last_modified_time=getattr(row, "zoho_last_modified_time", None),
        zoho_raw_hash=getattr(row, "zoho_raw_hash", None),
        sync_source=getattr(row, "sync_source", None),
        remote_deleted_at=getattr(row, "remote_deleted_at", None),
        deleted_at=getattr(row, "deleted_at", None),
        legacy_tombstone=getattr(row, "sync_status", None) == SyncStatus.DELETED.value,
    )


def _state_row_state(state: _CrosswalkState) -> RowState:
    """The gate's view of a crosswalk row — the same RowState, different source.

    ``apply.py`` is untouched by the crosswalk work: it still receives a
    RowState and still decides with the same table. That it needed no edits is
    the evidence the original gate/storage split was drawn in the right place.
    """
    return RowState(
        zoho_last_modified_time=state.source_modified_at,
        zoho_raw_hash=state.raw_hash,
        sync_source=state.raw_source,
        remote_deleted_at=state.remote_deleted_at,
        deleted_at=state.entity_deleted_at,
        legacy_tombstone=False,          # a crosswalk row never carries v1 sync_status
    )


def _already_current(stored: _StoredVersion, record: dict) -> bool:
    """True when the stored row is the detail document of the listed version."""
    listed = parse_zoho_datetime(record.get("last_modified_time"))
    return (
        listed is not None
        and not stored.tombstoned
        and stored.modified == listed
        and provenance_rank(stored.source) >= 2
    )


def _budget_hit(cfg, report: SyncRunReport, started: float) -> str | None:
    """The slice budget that says "stop here", if any (0 = unlimited)."""
    if cfg.max_run_seconds and (time.perf_counter() - started) >= cfg.max_run_seconds:
        return "budget:max_run_seconds"
    if cfg.max_pages_per_run and report.pages >= cfg.max_pages_per_run:
        return "budget:max_pages"
    if cfg.max_records_per_run and report.listed >= cfg.max_records_per_run:
        return "budget:max_records"
    return None
