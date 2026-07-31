"""Activity module — read-only HTTP endpoints.

The audit trail is WRITTEN internally (recorder.record_activity); it is never
created through the API. These endpoints expose it for an admin/audit view.
"""

import uuid

from fastapi import APIRouter, Query

from app.common.response.schema import PageModel, ResponseModel
from app.database.db import DBSession
from app.modules.activity import service
from app.modules.activity.schema import ActivityListFilters, ActivityLogOut
from app.modules.users.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=ResponseModel[PageModel[ActivityLogOut]])
async def list_activity(db: DBSession, _: CurrentUser, filters: ActivityListFilters = Query()):
    rows, total = await service.list_activity(db, filters)
    return ResponseModel(
        data=PageModel(
            items=[ActivityLogOut.model_validate(r) for r in rows],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@router.get("/{activity_id}", response_model=ResponseModel[ActivityLogOut])
async def get_activity(db: DBSession, _: CurrentUser, activity_id: uuid.UUID):
    row = await service.get_activity(db, activity_id)
    return ResponseModel(data=ActivityLogOut.model_validate(row))
