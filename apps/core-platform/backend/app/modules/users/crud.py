"""Users module — data access (crud layer). No business logic here."""

from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.model import PasswordResetToken, User


def _base_query(include_deleted: bool = False) -> Select:
    query = select(User)
    if not include_deleted:
        query = query.where(User.deleted_at.is_(None))
    return query


async def get_by_id(db: AsyncSession, user_id: int, *, include_deleted: bool = False) -> User | None:
    return await db.scalar(_base_query(include_deleted).where(User.id == user_id))


async def get_by_email(db: AsyncSession, email: str, *, include_deleted: bool = False) -> User | None:
    return await db.scalar(_base_query(include_deleted).where(func.lower(User.email) == email.lower()))


async def get_by_username(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(_base_query().where(User.username == username))


async def get_by_external_id(db: AsyncSession, external_id: str) -> User | None:
    return await db.scalar(_base_query().where(User.external_id == external_id))


async def list_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    user_type: str | None = None,
    role_id: int | None = None,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    include_deleted: bool = False,
    page: int = 1,
    page_size: int = 50,
    order_by: str = "-created_at",
) -> tuple[list[User], int]:
    query = _base_query(include_deleted)

    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                User.name.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
                User.phone.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
            )
        )
    if status:
        query = query.where(User.status == status)
    if user_type:
        query = query.where(User.user_type == user_type)
    if role_id is not None:
        query = query.where(User.role_id == role_id)
    if city:
        query = query.where(User.city == city)
    if state:
        query = query.where(User.state == state)
    if country:
        query = query.where(User.country == country)

    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0

    descending = order_by.startswith("-")
    column = getattr(User, order_by.lstrip("-"), User.created_at)
    query = query.order_by(column.desc() if descending else column.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    users = (await db.scalars(query)).all()
    return list(users), total


async def create(db: AsyncSession, values: dict) -> User:
    user = User(**values)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def update(db: AsyncSession, user: User, values: dict) -> User:
    for key, value in values.items():
        setattr(user, key, value)
    await db.flush()
    await db.refresh(user)
    return user


async def soft_delete(db: AsyncSession, user: User, *, deleted_by: int | None = None) -> User:
    user.deleted_at = datetime.now(UTC)
    user.deleted_by = deleted_by
    await db.flush()
    return user


async def restore(db: AsyncSession, user: User) -> User:
    user.deleted_at = None
    user.deleted_by = None
    await db.flush()
    return user


async def hard_delete(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.flush()


# ── Password reset tokens ─────────────────────────────────────────────────────

async def upsert_reset_token(
    db: AsyncSession, *, email: str, token: str, reset_type: str, code: str | None
) -> PasswordResetToken:
    existing = await db.get(PasswordResetToken, email)
    if existing:
        existing.token = token
        existing.reset_type = reset_type
        existing.code = code
        existing.created_at = datetime.now(UTC)
        await db.flush()
        return existing
    row = PasswordResetToken(email=email, token=token, reset_type=reset_type, code=code)
    db.add(row)
    await db.flush()
    return row


async def get_reset_token(db: AsyncSession, email: str) -> PasswordResetToken | None:
    return await db.get(PasswordResetToken, email)


async def delete_reset_token(db: AsyncSession, email: str) -> None:
    row = await db.get(PasswordResetToken, email)
    if row:
        await db.delete(row)
        await db.flush()
