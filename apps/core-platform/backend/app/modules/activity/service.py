"""Activity module — business logic (read side).

Writing audit entries is done via recorder.record_activity (imported by other
modules). This service covers querying the trail for the admin/audit UI.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import NotFoundError
from app.modules.activity import crud
from app.modules.activity.model import ActivityLog
from app.modules.activity.schema import ActivityListFilters


async def list_activity(db: AsyncSession, filters: ActivityListFilters) -> tuple[list[ActivityLog], int]:
    return await crud.list_activity(db, filters)


async def get_activity(db: AsyncSession, activity_id) -> ActivityLog:
    row = await crud.get_by_uuid(db, activity_id)
    if row is None:
        raise NotFoundError(f"Activity {activity_id} not found")
    return row
