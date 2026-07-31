"""Sync-engine admin API (mounted at /api/zoho/sync-engine, JWT-protected).

Operational surface for the sync pipeline:
  GET  /modules                     every registered module + live stats
  POST /modules/{module}/run        trigger a run (mode=full|incremental|index)
  GET  /modules/{module}/stats      table-level counters & cursors
  GET  /modules/{module}/queue-logs row-level journal (filter by status)
"""

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.common.exception.errors import NotFoundError
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.users.deps import CurrentUser
from app.modules.zoho.sync.config import SyncStrategyName
from app.modules.zoho.sync.models import ZohoQueueLog, ZohoSyncStat
from app.modules.zoho.sync.registry import sync_registry
from app.modules.zoho.sync.schemas import ModuleInfoOut, QueueLogOut, SyncRunAccepted, SyncStatOut

router = APIRouter()


@router.get("/modules", response_model=ResponseModel[list[ModuleInfoOut]])
async def list_modules(_: CurrentUser, db: DBSession):
    stats = {s.module_name: s for s in (await db.scalars(select(ZohoSyncStat))).all()}
    out = []
    for defn in sync_registry.all():
        cfg = defn.config
        stat = stats.get(defn.name)
        out.append(
            ModuleInfoOut(
                module=defn.name,
                endpoint=cfg.endpoint,
                strategy=cfg.strategy.value,
                direction=cfg.direction.value,
                detail_required=cfg.detail_required,
                detail_dispatch=cfg.detail_dispatch,
                batch_size=cfg.batch_size,
                sync_interval_minutes=cfg.sync_interval_minutes,
                enabled=cfg.enabled,
                field_count=len(cfg.field_map),
                nested_modules=[n.module for n in cfg.nested],
                stats=SyncStatOut.model_validate(stat) if stat else None,
            )
        )
    return ResponseModel(data=out)


@router.post("/modules/{module}/run", response_model=ResponseModel[SyncRunAccepted], status_code=202)
async def trigger_run(
    _: CurrentUser,
    module: str,
    mode: SyncStrategyName | None = Query(None, description="Override the configured strategy"),
):
    defn = sync_registry.get(module)  # raises NotFoundError for unknown modules
    from app.tasks.zoho_sync import sync_module

    result = sync_module.delay(defn.name, mode.value if mode else None)
    return ResponseModel(
        data=SyncRunAccepted(module=defn.name, mode=(mode or defn.config.strategy).value, task_id=result.id),
        msg="Sync run queued",
    )


@router.get("/modules/{module}/stats", response_model=ResponseModel[SyncStatOut])
async def module_stats(_: CurrentUser, db: DBSession, module: str):
    sync_registry.get(module)
    stat = await db.scalar(select(ZohoSyncStat).where(ZohoSyncStat.module_name == module))
    if stat is None:
        raise NotFoundError(f"No sync runs recorded yet for '{module}'")
    return ResponseModel(data=SyncStatOut.model_validate(stat))


@router.get("/modules/{module}/queue-logs", response_model=ResponseModel[list[QueueLogOut]])
async def module_queue_logs(
    _: CurrentUser,
    db: DBSession,
    module: str,
    status: str | None = Query(None, pattern="^(queued|processing|success|failed|skipped)$"),
    limit: int = Query(100, ge=1, le=1000),
):
    sync_registry.get(module)
    stmt = select(ZohoQueueLog).where(ZohoQueueLog.module_name == module)
    if status:
        stmt = stmt.where(ZohoQueueLog.status == status)
    stmt = stmt.order_by(ZohoQueueLog.id.desc()).limit(limit)
    rows = (await db.scalars(stmt)).all()
    return ResponseModel(data=[QueueLogOut.model_validate(r) for r in rows])
