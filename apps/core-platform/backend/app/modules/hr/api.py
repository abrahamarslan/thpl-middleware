"""HR HTTP API — mounted at /api/hr.

| Route | Permission |
|---|---|
| ``GET /employment`` | ``hr.employment:read`` |
| ``GET /employment/{id}`` | ``hr.employment:read`` (at the record's organization/department) |
| ``POST /employment`` | ``hr.employment:create`` |
| ``PATCH /employment/{id}`` | ``hr.employment:update`` — placement (department, job title, manager) and dates |
| ``POST /employment/{id}/end`` | ``hr.employment:update`` — close the stint (kept as history) |
| ``GET /org-chart`` | ``hr.employment:read`` — the reporting tree of current employment |

Statutory / payroll / onboarding fields are deliberately not exposed here.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.hr import service
from app.modules.hr.deps import employment_target
from app.modules.hr.schema import (
    EmploymentCreate,
    EmploymentEnd,
    EmploymentOut,
    EmploymentUpdate,
    OrgChartNode,
)
from app.modules.rbac.deps import Perm

router = APIRouter()
_M = "hr"


async def _org_id(db, ref: str | None) -> int | None:
    if not ref:
        return None
    from app.modules.organizations import service as orgs

    return (await orgs.get_organization(db, ref)).id


@router.get("/employment", response_model=ResponseModel[PageModel[EmploymentOut]])
async def list_employment(
    _: Perm("hr.employment:read"), db: DBSession,
    user_id: int | None = Query(None, gt=0), department: str | None = Query(None),
    is_current: bool | None = Query(None), status: str | None = Query(None, max_length=30),
    manager_user_id: int | None = Query(None, gt=0), organization: str | None = Query(None),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
):
    rows, total = await service.list_employment(
        db, user_id=user_id, department=department, is_current=is_current, status=status,
        manager_user_id=manager_user_id, organization=await _org_id(db, organization),
        page=page, page_size=page_size)
    return ResponseModel(data=PageModel(
        items=[EmploymentOut.model_validate(r) for r in rows], page=page, page_size=page_size, total=total,
        has_more=page * page_size < total))


@router.get("/org-chart", response_model=ResponseModel[list[OrgChartNode]])
async def org_chart(_: Perm("hr.employment:read"), db: DBSession, organization: str | None = Query(None)):
    return ResponseModel.ok(data=await service.org_chart(db, await _org_id(db, organization)))


@router.post("/employment", response_model=ResponseModel[EmploymentOut], status_code=201)
async def create_employment(actor: Perm("hr.employment:create"), db: DBSession, body: EmploymentCreate):
    row = await service.create_employment(db, body, actor=actor)
    return ResponseModel.ok(data=EmploymentOut.model_validate(row), module=_M, msg_key="employment_created",
                            code=row.employee_code)


@router.get("/employment/{record_id}", response_model=ResponseModel[EmploymentOut])
async def get_employment(_: Perm("hr.employment:read", target=employment_target), db: DBSession, record_id: int):
    return ResponseModel.ok(data=EmploymentOut.model_validate(await service.get_employment(db, record_id)))


@router.patch("/employment/{record_id}", response_model=ResponseModel[EmploymentOut])
async def update_employment(
    actor: Perm("hr.employment:update", target=employment_target), db: DBSession, record_id: int,
    body: EmploymentUpdate,
):
    row = await service.update_employment(db, record_id, body, actor=actor)
    return ResponseModel.ok(data=EmploymentOut.model_validate(row), module=_M, msg_key="employment_updated",
                            code=row.employee_code)


@router.post("/employment/{record_id}/end", response_model=ResponseModel[EmploymentOut])
async def end_employment(
    actor: Perm("hr.employment:update", target=employment_target), db: DBSession, record_id: int,
    body: EmploymentEnd,
):
    row = await service.end_employment(db, record_id, body, actor=actor)
    return ResponseModel.ok(data=EmploymentOut.model_validate(row), module=_M, msg_key="employment_ended",
                            code=row.employee_code)
