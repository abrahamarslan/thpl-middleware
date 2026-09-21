"""Zoho operator API — mounted at /api/zoho/admin (operators only).

Read:  health · governor · switches · runs · run detail · record history · retention ·
       module config (effective value + layer per knob)
Act:   set a switch · pause/resume a module · request a run · reset a breaker ·
       change a retention policy · set/clear a module config override

Every action requires a reason and is written to ``activity_logs``.
Docs: docs/zoho-sync-implementation/operator-api.md
"""

import uuid

from fastapi import APIRouter, Query, Request

from app.common.client_info import client_ip_from_request
from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.zoho.admin import crud, service
from app.modules.zoho.admin.deps import ZohoOperator
from app.modules.zoho.admin.schema import (
    ConfigUpdate,
    HealthOut,
    ModulePauseRequest,
    RetentionPolicyOut,
    RetentionPolicyUpdate,
    RunOut,
    RunRequest,
    RunSlimOut,
    SwitchUpdate,
    SyncEventOut,
)
from app.modules.zoho.core.governor import zoho_governor

router = APIRouter()
_M = "zoho.admin"


@router.get("/health", response_model=ResponseModel[HealthOut])
async def health(_: ZohoOperator, db: DBSession):
    return ResponseModel.ok(data=await service.health(db))


@router.get("/governor", response_model=ResponseModel[dict])
async def governor(_: ZohoOperator):
    return ResponseModel.ok(data=await zoho_governor.snapshot())


@router.get("/switches", response_model=ResponseModel[dict])
async def switches(_: ZohoOperator):
    from app.modules.zoho.control.switches import zoho_switches

    return ResponseModel.ok(data=(await zoho_switches.snapshot()).as_dict())


@router.put("/switches/{name}", response_model=ResponseModel[dict])
async def set_switch(operator: ZohoOperator, db: DBSession, request: Request, name: str, body: SwitchUpdate):
    data = await service.set_switch(
        db, name, body.value, operator=operator, reason=body.reason, ip=client_ip_from_request(request)
    )
    return ResponseModel.ok(data=data, module=_M, msg_key="switch_changed", name=name)


@router.post("/modules/{module}/pause", response_model=ResponseModel[dict])
async def pause_module(operator: ZohoOperator, db: DBSession, request: Request, module: str,
                       body: ModulePauseRequest):
    data = await service.pause_module(db, module, pause=True, operator=operator, reason=body.reason,
                                      ip=client_ip_from_request(request))
    return ResponseModel.ok(data=data, module=_M, msg_key="module_paused", name=module)


@router.post("/modules/{module}/resume", response_model=ResponseModel[dict])
async def resume_module(operator: ZohoOperator, db: DBSession, request: Request, module: str,
                        body: ModulePauseRequest):
    data = await service.pause_module(db, module, pause=False, operator=operator, reason=body.reason,
                                      ip=client_ip_from_request(request))
    return ResponseModel.ok(data=data, module=_M, msg_key="module_resumed", name=module)


@router.post("/modules/{module}/runs", response_model=ResponseModel[dict], status_code=202)
async def request_run(operator: ZohoOperator, db: DBSession, module: str, body: RunRequest):
    data = await service.request_run(db, module, mode=body.mode, operator=operator, reason=body.reason)
    return ResponseModel.ok(data=data, module=_M, msg_key="run_requested", name=module)


@router.get("/runs", response_model=ResponseModel[list[RunSlimOut]])
async def list_runs(
    _: ZohoOperator,
    db: DBSession,
    module: str | None = Query(None),
    lane: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    rows = await crud.list_runs(db, module=module, lane=lane, status=status, limit=limit)
    return ResponseModel.ok(data=[RunSlimOut.model_validate(r) for r in rows])


@router.get("/runs/{run_id}", response_model=ResponseModel[RunOut])
async def get_run(_: ZohoOperator, db: DBSession, run_id: uuid.UUID):
    return ResponseModel.ok(data=RunOut.model_validate(await service.get_run(db, run_id)))


@router.get("/records/{module}/{ref}/events", response_model=ResponseModel[list[SyncEventOut]])
async def record_events(
    _: ZohoOperator,
    db: DBSession,
    module: str,
    ref: str,
    by: str = Query("local", pattern="^(local|zoho)$"),
    event_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """What happened to one record: "inserted", "updated (status, total)", …"""
    rows = await service.record_history(db, module, ref, by=by, event_type=event_type, limit=limit)
    return ResponseModel.ok(data=[SyncEventOut.model_validate(r) for r in rows])


@router.get("/retention", response_model=ResponseModel[list[RetentionPolicyOut]])
async def list_retention(_: ZohoOperator, db: DBSession):
    return ResponseModel.ok(data=[RetentionPolicyOut.model_validate(p) for p in await crud.list_policies(db)])


@router.put("/retention/{policy_id}", response_model=ResponseModel[RetentionPolicyOut])
async def update_retention(operator: ZohoOperator, db: DBSession, policy_id: int, body: RetentionPolicyUpdate):
    policy = await service.update_policy(
        db, policy_id, keep_days=body.keep_days, enabled=body.enabled, operator=operator, reason=body.reason
    )
    return ResponseModel.ok(data=RetentionPolicyOut.model_validate(policy), module=_M, msg_key="retention_changed")


@router.get("/config/{module}", response_model=ResponseModel[dict])
async def get_module_config(_: ZohoOperator, db: DBSession, module: str):
    """Every runtime knob: effective value and the layer that supplied it."""
    return ResponseModel.ok(data=await service.module_config(db, module))


@router.put("/config/{module}/{knob}", response_model=ResponseModel[dict])
async def set_module_config(operator: ZohoOperator, db: DBSession, request: Request, module: str, knob: str,
                            body: ConfigUpdate):
    data = await service.set_module_config(
        db, module, knob, body.value, operator=operator, reason=body.reason, ip=client_ip_from_request(request)
    )
    return ResponseModel.ok(data=data, module=_M, msg_key="config_changed", name=f"{module}.{knob}")


@router.delete("/config/{module}/{knob}", response_model=ResponseModel[dict])
async def clear_module_config(operator: ZohoOperator, db: DBSession, request: Request, module: str, knob: str,
                              reason: str = Query(..., min_length=3, max_length=500)):
    """Remove an override — the module's declared value applies again."""
    data = await service.clear_module_config(
        db, module, knob, operator=operator, reason=reason, ip=client_ip_from_request(request)
    )
    return ResponseModel.ok(data=data, module=_M, msg_key="config_cleared", name=f"{module}.{knob}")


@router.post("/breakers/{group}/reset", response_model=ResponseModel[dict])
async def reset_breaker(operator: ZohoOperator, db: DBSession, group: str):
    data = await service.reset_breaker(group, operator=operator, db=db)
    return ResponseModel.ok(data=data, module=_M, msg_key="breaker_reset", name=group)
