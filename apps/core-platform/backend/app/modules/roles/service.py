"""Roles business logic — organization-scoped (inside the caller's tenant)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AppError, ConflictError, NotFoundError
from app.database.tenancy import current_organization_id
from app.modules.activity.recorder import record_activity
from app.modules.roles.model import SYSTEM_ROLES, Role
from app.modules.roles.schema import RoleCreate, RoleUpdate


class RoleRuleError(AppError):
    status_code = 422
    code = "role_rule_violation"


async def list_roles(db: AsyncSession) -> list[Role]:
    return list((await db.scalars(select(Role).order_by(Role.is_system.desc(), Role.code))).all())


async def get_role(db: AsyncSession, ref: str) -> Role:
    cond = Role.id == int(ref) if str(ref).isdigit() else Role.code == str(ref)
    role = await db.scalar(select(Role).where(cond).limit(1))
    if role is None:
        raise NotFoundError(f"Role '{ref}' not found")
    return role


def _require_org() -> int:
    organization_id = current_organization_id()
    if organization_id is None:
        raise RoleRuleError(
            "No organization is bound to this request; choose one with the 'X-Organization-Id' header.",
            data={"hint": "GET /api/organizations lists them"},
        )
    return organization_id


async def create_role(db: AsyncSession, body: RoleCreate, *, actor_id: int | None) -> Role:
    organization_id = _require_org()
    if await db.scalar(select(Role.id).where(
        Role.organization_id == organization_id, func.lower(Role.code) == body.code.lower()
    )):
        raise ConflictError(f"Role code '{body.code}' already exists in this organization")
    role = Role(**body.model_dump(), organization_id=organization_id)
    db.add(role)
    await db.flush()
    await record_activity(db, action="role_created", actor_id=actor_id, subject_type="Role", subject_id=role.id,
                          changes={"after": body.model_dump()})
    return role


async def update_role(db: AsyncSession, ref: str, body: RoleUpdate, *, actor_id: int | None) -> Role:
    role = await get_role(db, ref)
    if role.row_version != body.row_version:
        raise ConflictError(f"Role '{role.code}' changed since you loaded it; reload and retry",
                            data={"current_row_version": role.row_version})
    changes = body.model_dump(exclude_unset=True, exclude={"row_version"})
    for field, value in changes.items():
        setattr(role, field, value)
    await db.flush()
    await record_activity(db, action="role_updated", actor_id=actor_id, subject_type="Role", subject_id=role.id,
                          changes={"after": changes})
    return role


async def delete_role(db: AsyncSession, ref: str, *, reason: str, actor_id: int | None) -> None:
    from app.modules.users.model import User

    role = await get_role(db, ref)
    if role.is_system:
        raise RoleRuleError(f"'{role.code}' is a system role and cannot be deleted")
    holders = await db.scalar(select(func.count()).select_from(User).where(
        User.role_id == role.id, User.organization_id == role.organization_id
    ))
    if holders:
        raise RoleRuleError(f"{holders} user(s) still hold role '{role.code}'; reassign them first")
    role.soft_delete(reason=reason, by=actor_id)
    await db.flush()
    await record_activity(db, action="role_deleted", actor_id=actor_id, subject_type="Role", subject_id=role.id,
                          context={"reason": reason})


async def seed_system_roles(db: AsyncSession, organization_id: int) -> list[Role]:
    """Idempotent: create the missing system roles for one organization."""
    existing = set((await db.scalars(
        select(Role.code).where(Role.organization_id == organization_id)
    )).all())
    created = []
    for code, name, description in SYSTEM_ROLES:
        if code not in existing:
            role = Role(
                code=code, name=name, description=description, is_system=True,
                organization_id=organization_id,
            )
            db.add(role)
            created.append(role)
    await db.flush()
    return created
