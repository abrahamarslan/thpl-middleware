"""Employment business logic — stint lifecycle, placement and the reporting line.

Deliberately small: create/update/end a stint, place the person (department, job title, manager)
and read the org chart. Statutory, payroll and onboarding concerns stay out (docs/rbac-module.md §5.5).

Rules:
* one CURRENT stint per user (a partial unique index says so; the service says it nicely first);
* a department / job title must belong to the SAME organization as the record;
* a job title tied to a department cannot be combined with a different department;
* the reporting line is acyclic — the chain of current managers is walked (capped) before a manager is set;
* ending a stint keeps it (history) and clears ``is_current``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.common.serialization import to_jsonable
from app.database import scope
from app.modules.activity.recorder import record_activity
from app.modules.hr.model import EmploymentRecord

#: Longest reporting chain we will walk before calling it a cycle.
MAX_CHAIN = 100


class HrRuleError(AppError):
    status_code = 422
    code = "hr_rule_violation"


async def require_organization(db: AsyncSession) -> int:
    try:
        return await scope.require_organization_id(db)
    except scope.OrganizationRequiredError as exc:
        raise HrRuleError(exc.msg, data=exc.data) from exc


async def get_employment(db: AsyncSession, record_id: int) -> EmploymentRecord:
    row = await db.scalar(select(EmploymentRecord).where(EmploymentRecord.id == record_id))
    if row is None:
        raise NotFoundError(f"Employment record {record_id} not found")
    return row


async def list_employment(
    db: AsyncSession, *, user_id: int | None, department: str | None, is_current: bool | None,
    status: str | None, manager_user_id: int | None, organization: int | None, page: int, page_size: int,
) -> tuple[list[EmploymentRecord], int]:
    from app.modules.teams import service as teams

    stmt = select(EmploymentRecord).order_by(EmploymentRecord.date_of_joining.desc(), EmploymentRecord.id)
    if user_id is not None:
        stmt = stmt.where(EmploymentRecord.user_id == user_id)
    if organization is not None:
        stmt = stmt.where(EmploymentRecord.organization_id == organization)
    if department is not None:
        stmt = stmt.where(EmploymentRecord.department_id == (await teams.get_department(db, department)).id)
    if is_current is not None:
        stmt = stmt.where(EmploymentRecord.is_current.is_(is_current))
    if status:
        stmt = stmt.where(EmploymentRecord.employment_status == status)
    if manager_user_id is not None:
        stmt = stmt.where(EmploymentRecord.reporting_manager_user_id == manager_user_id)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = (await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return list(rows), total


async def _existing_user(db: AsyncSession, user_id: int, what: str) -> Any:
    from app.modules.users import crud as users_crud

    user = await users_crud.get_by_id(db, user_id)
    if user is None:
        raise NotFoundError(f"{what} {user_id} not found")
    return user


async def _placement(
    db: AsyncSession, organization_id: int, department: str | None, job_title: str | None,
) -> tuple[int | None, int | None]:
    """Resolve department / job title refs inside ``organization_id`` and check they agree."""
    from app.modules.teams import service as teams

    dept = await teams.get_department(db, department) if department else None
    title = await teams.get_job_title(db, job_title) if job_title else None
    for row, label in ((dept, "department"), (title, "job title")):
        if row is not None and row.organization_id != organization_id:
            raise HrRuleError(f"The {label} belongs to a different organization than the employment record")
    if dept is not None and title is not None and title.department_id not in (None, dept.id):
        raise HrRuleError(f"Job title '{title.job_code}' belongs to a different department")
    return (dept.id if dept else None), (title.id if title else None)


async def _refuse_reporting_cycle(db: AsyncSession, user_id: int, manager_user_id: int) -> None:
    """Walk up the chain of CURRENT managers; reaching ``user_id`` means the new line would loop."""
    if manager_user_id == user_id:
        raise HrRuleError("A person cannot report to themselves")
    seen: set[int] = set()
    current: int | None = manager_user_id
    for _ in range(MAX_CHAIN):
        if current is None:
            return
        if current == user_id:
            raise HrRuleError("That reporting line would create a loop (the manager already reports to this person)")
        if current in seen:
            return                                   # an existing loop elsewhere; not ours to fix here
        seen.add(current)
        current = await db.scalar(select(EmploymentRecord.reporting_manager_user_id).where(
            EmploymentRecord.user_id == current, EmploymentRecord.is_current.is_(True)))
    raise HrRuleError("The reporting chain is implausibly deep; refusing to extend it")


async def create_employment(db: AsyncSession, body: Any, *, actor: Any) -> EmploymentRecord:
    organization_id = await require_organization(db)
    await _existing_user(db, body.user_id, "User")
    if await db.scalar(select(EmploymentRecord.id).where(
        EmploymentRecord.user_id == body.user_id, EmploymentRecord.is_current.is_(True))):
        raise ConflictError("This user already has a current employment record; end it before starting another",
                            data={"user_id": body.user_id})
    if await db.scalar(select(EmploymentRecord.id).where(
        func.lower(EmploymentRecord.employee_code) == body.employee_code.lower())):
        raise ConflictError(f"Employee code '{body.employee_code}' is already in use")
    department_id, job_title_id = await _placement(db, organization_id, body.department, body.job_title)
    if body.reporting_manager_user_id:
        await _existing_user(db, body.reporting_manager_user_id, "Manager")
        await _refuse_reporting_cycle(db, body.user_id, body.reporting_manager_user_id)
    values = body.model_dump(exclude={"department", "job_title"})
    for key in ("personnel_type", "employment_type", "employment_status", "work_location_type"):
        if values.get(key) is not None:
            values[key] = values[key].value
    row = EmploymentRecord(**values, organization_id=organization_id, is_current=True,
                           department_id=department_id, job_title_id=job_title_id)
    db.add(row)
    await db.flush()
    await record_activity(db, action="employment_created", actor_id=actor.id, subject_type="EmploymentRecord",
                          subject_id=row.id, changes={"after": {"user_id": row.user_id, "code": row.employee_code}})
    return row


async def update_employment(db: AsyncSession, record_id: int, body: Any, *, actor: Any) -> EmploymentRecord:
    row = await get_employment(db, record_id)
    if row.row_version != body.row_version:
        raise ConflictError("The employment record changed since you loaded it; reload and retry",
                            data={"current_row_version": row.row_version})
    if not row.is_current:
        raise HrRuleError("An ended employment record is history and cannot be edited")
    changes = body.model_dump(exclude_unset=True, exclude={"row_version", "department", "job_title"})
    for key in ("personnel_type", "employment_type", "employment_status", "work_location_type"):
        if changes.get(key) is not None:
            changes[key] = changes[key].value
    if {"department", "job_title"} & body.model_fields_set:
        dept_ref = body.department if "department" in body.model_fields_set else None
        title_ref = body.job_title if "job_title" in body.model_fields_set else None
        # An unspecified side keeps its current value; check the pair as it will be.
        if "department" not in body.model_fields_set and row.department_id:
            dept_ref = str(row.department_id)
        if "job_title" not in body.model_fields_set and row.job_title_id:
            title_ref = str(row.job_title_id)
        department_id, job_title_id = await _placement(db, row.organization_id, dept_ref or None, title_ref or None)
        changes["department_id"], changes["job_title_id"] = department_id, job_title_id
    manager = changes.get("reporting_manager_user_id")
    if manager:
        await _existing_user(db, manager, "Manager")
        await _refuse_reporting_cycle(db, row.user_id, manager)
    before = {k: getattr(row, k) for k in changes}
    for field, value in changes.items():
        setattr(row, field, value)
    await db.flush()
    await record_activity(db, action="employment_updated", actor_id=actor.id, subject_type="EmploymentRecord",
                          subject_id=row.id, changes={"before": to_jsonable(before), "after": to_jsonable(changes)})
    return row


async def end_employment(db: AsyncSession, record_id: int, body: Any, *, actor: Any) -> EmploymentRecord:
    row = await get_employment(db, record_id)
    if row.row_version != body.row_version:
        raise ConflictError("The employment record changed since you loaded it; reload and retry",
                            data={"current_row_version": row.row_version})
    if not row.is_current:
        raise HrRuleError("This employment record has already ended")
    if body.date_of_exit < row.date_of_joining:
        raise HrRuleError("date_of_exit cannot be before date_of_joining")
    row.is_current = False
    row.date_of_exit = body.date_of_exit
    row.exit_reason = body.exit_reason
    row.employment_status = body.employment_status.value
    row.rehire_eligible = body.rehire_eligible
    await db.flush()
    await record_activity(db, action="employment_ended", actor_id=actor.id, subject_type="EmploymentRecord",
                          subject_id=row.id, changes={"after": {"status": row.employment_status,
                                                                "date_of_exit": row.date_of_exit.isoformat()}})
    return row


async def org_chart(db: AsyncSession, organization: int | None) -> list[dict[str, Any]]:
    """The reporting tree of CURRENT employment: roots are people with no (current) manager."""
    from app.modules.users.model import User

    stmt = select(EmploymentRecord, User.name).join(User, User.id == EmploymentRecord.user_id).where(
        EmploymentRecord.is_current.is_(True))
    if organization is not None:
        stmt = stmt.where(EmploymentRecord.organization_id == organization)
    rows = (await db.execute(stmt)).all()
    nodes = {
        rec.user_id: {"user_id": rec.user_id, "name": name, "employee_code": rec.employee_code,
                      "department_id": rec.department_id, "job_title_id": rec.job_title_id, "reports": []}
        for rec, name in rows
    }
    roots: list[dict[str, Any]] = []
    for rec, _ in rows:
        parent = nodes.get(rec.reporting_manager_user_id) if rec.reporting_manager_user_id else None
        (parent["reports"] if parent else roots).append(nodes[rec.user_id])
    return roots


__all__ = [
    "HrRuleError", "create_employment", "end_employment", "get_employment", "list_employment",
    "org_chart", "update_employment",
]
