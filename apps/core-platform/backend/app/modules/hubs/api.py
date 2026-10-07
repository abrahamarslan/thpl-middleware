"""Hub API — mounted at /api/hubs (the caller's tenant + organization)."""

import datetime as dt

from fastapi import APIRouter, Query

from app.common.exception.errors import NotFoundError

from app.common.response.schema import ResponseModel
from app.database.db import DBSession
from app.modules.hubs import assignments, service
from app.modules.hubs.schema import (
    HubAssignmentOut,
    HubAssignmentsIn,
    HubCreate,
    HubOfDayOut,
    HubOut,
    HubSlim,
    HubUpdate,
)
from app.modules.rbac.deps import GrantsDep, Perm, org_of
from app.modules.rbac.engine import Target
from app.modules.users.deps import CurrentUser

router = APIRouter()
_M = "hubs"


@router.get("", response_model=ResponseModel[list[HubSlim]])
async def list_hubs(
    _: CurrentUser,
    db: DBSession,
    hub_type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    rows = await service.list_hubs(db, hub_type=hub_type, status=status, q=q, page=page, page_size=page_size)
    return ResponseModel.ok(data=[HubSlim.model_validate(r) for r in rows], module=_M, msg_key="listed")


# ── user hub assignments (registered before /{ref}) ─────────────────────────────

@router.get("/assignments", response_model=ResponseModel[list[HubAssignmentOut]])
async def list_assignments(_: Perm("hubs.assignment:read"), db: DBSession, grants: GrantsDep,
                           user_id: int | None = None, hub_id: int | None = None, date: dt.date | None = None):
    """Assignments of the users whose organization the caller's ``hubs.assignment:read`` covers."""
    rows = await assignments.list_assignments(db, user_id=user_id, hub_id=hub_id, day=date)
    allowed: dict[int, bool] = {}
    for org_id in {r.organization_id for r in rows}:
        allowed[org_id] = await grants.allows(db, "hubs.assignment:read", Target(organization_id=org_id))
    return ResponseModel(data=[HubAssignmentOut.model_validate(r) for r in rows if allowed[r.organization_id]])


@router.post("/assignments", response_model=ResponseModel[list[HubAssignmentOut]], status_code=201)
async def set_assignments(_: Perm("hubs.assignment:manage"), db: DBSession, grants: GrantsDep,
                          body: HubAssignmentsIn):
    """Set users' hubs by day or range (all-or-nothing). Overlapped assignments are split, not refused.

    Authorized PER USER at that user's organization (a branch manager cannot move another branch's
    people); one refused item refuses the whole request."""
    from sqlalchemy import select

    from app.modules.users.model import User

    users = []
    for item in body.assignments:
        try:
            item.window()
        except ValueError as exc:
            raise assignments.HubAssignmentError(str(exc), data={"user_id": item.user_id}) from None
        user = await db.scalar(select(User).where(User.id == item.user_id))
        if user is None:
            raise NotFoundError(f"User {item.user_id} not found")
        users.append(user)
    await grants.require_all(db, "hubs.assignment:manage", [Target(organization_id=u.organization_id) for u in users])
    out = []
    for item, user in zip(body.assignments, users, strict=True):
        start, end = item.window()
        out.append(await assignments.assign(db, user=user, hub_id=item.hub_id, valid_from=start, valid_to=end,
                                            note=item.note))
    return ResponseModel(data=[HubAssignmentOut.model_validate(r) for r in out], msg="Hub assignments saved")


@router.get("/me", response_model=ResponseModel[HubOfDayOut])
async def my_hub(user: CurrentUser, db: DBSession, date: dt.date | None = None):
    """My hub for a day (default: today in my organization's timezone)."""
    day = date or await assignments.organization_today(db, user.organization_id)
    found = await assignments.hub_of_day(db, tenant_id=user.tenant_id, user_id=user.id, day=day)
    hub = await service.get_hub(db, found.hub_id) if found.hub_id else None
    return ResponseModel(data=HubOfDayOut(date=day, hub_id=found.hub_id, source=found.source,
                                          hub=HubSlim.model_validate(hub) if hub else None))


@router.get("/{ref}", response_model=ResponseModel[HubOut])
async def get_hub(_: CurrentUser, db: DBSession, ref: str):
    return ResponseModel.ok(data=HubOut.model_validate(await service.get_hub(db, ref)), module=_M, msg_key="fetched")


@router.post("", response_model=ResponseModel[HubOut], status_code=201)
async def create_hub(user: Perm("hubs.hub:create"), db: DBSession, body: HubCreate):
    hub = await service.create_hub(db, body, actor_id=user.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="created", code=hub.code)


@router.patch("/{ref}", response_model=ResponseModel[HubOut])
async def update_hub(user: Perm("hubs.hub:update", target=org_of("app.modules.hubs.model:Hub", "code")), db: DBSession, ref: str, body: HubUpdate):
    hub = await service.update_hub(db, ref, body, actor_id=user.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="updated", code=hub.code)


@router.post("/{ref}/archive", response_model=ResponseModel[HubOut])
async def archive_hub(admin: Perm("hubs.hub:manage", target=org_of("app.modules.hubs.model:Hub", "code")), db: DBSession, ref: str,
                      reason: str = Query(..., min_length=3, max_length=500)):
    hub = await service.archive_hub(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=HubOut.model_validate(hub), module=_M, msg_key="archived", code=hub.code)


@router.delete("/{ref}", response_model=ResponseModel[None])
async def delete_hub(admin: Perm("hubs.hub:delete", target=org_of("app.modules.hubs.model:Hub", "code")), db: DBSession, ref: str,
                     reason: str = Query(..., min_length=3, max_length=500)):
    await service.delete_hub(db, ref, reason=reason, actor_id=admin.id)
    return ResponseModel.ok(data=None, module=_M, msg_key="deleted", code=ref)
