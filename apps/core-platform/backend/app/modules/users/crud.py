"""Users module — data access (crud layer). No business logic here."""

from datetime import UTC, datetime

from geoalchemy2 import WKTElement
from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.model import Place, PlaceLink
from app.modules.users.model import (
    LoginOtpToken,
    PasswordResetToken,
    User,
    UserLiveLocation,
    UserLocationPing,
)


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


async def get_by_phone(db: AsyncSession, phone: str, *, include_deleted: bool = False) -> User | None:
    return await db.scalar(
        _base_query(include_deleted).where(or_(User.phone == phone, User.contact == phone))
    )


async def get_by_external_id(db: AsyncSession, external_id: str) -> User | None:
    return await db.scalar(_base_query().where(User.external_id == external_id))


async def list_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    user_type: str | None = None,
    role_id: int | None = None,
    country_code: str | None = None,
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
    if country_code:
        query = query.where(User.country_code == country_code)
    # City/state/country moved off the users row onto the address book: they are
    # a property of the user's live address links, not of the user. EXISTS keeps
    # it one row per user no matter how many addresses match.
    if city or state or country:
        address = (
            select(PlaceLink.id)
            .join(Place, Place.id == PlaceLink.place_id)
            .where(
                PlaceLink.owner_type == "user",
                PlaceLink.owner_id == User.id,
                PlaceLink.deleted_at.is_(None),
                PlaceLink.valid_to.is_(None),
            )
        )
        if city:
            address = address.where(Place.city.ilike(city))
        if state:
            address = address.where(Place.state.ilike(state))
        if country:
            address = address.where(
                or_(Place.country.ilike(country), Place.country_code == country.upper())
            )
        query = query.where(address.exists())

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


def apply_values(user: User, values: dict) -> None:
    """Set attributes without flushing.

    Lets the service capture a field-level diff (``model_changes``) while the
    unit-of-work history is still populated, before the flush resets it.
    """
    for key, value in values.items():
        setattr(user, key, value)


async def update(db: AsyncSession, user: User, values: dict) -> User:
    apply_values(user, values)
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


# ── Location telemetry ────────────────────────────────────────────────────────
# Two tables, two write shapes: `user_live_locations` is one row per user,
# upserted on every fix; `user_location_pings` is append-only history. Both are
# written with Core statements (not the ORM) so a burst of fixes never drags a
# user object through the identity map — and because the upsert must be a single
# `INSERT ... ON CONFLICT` round trip, which is the whole point of the table.


def point(latitude: float, longitude: float) -> WKTElement:
    """WGS84 point. PostGIS is (longitude, latitude) — the inverse of how the
    wire format reads, which is the single most common bug in this area."""
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


async def upsert_live_location(db: AsyncSession, *, user: User, values: dict) -> UserLiveLocation:
    """Write the user's last known position (insert or update, one statement)."""
    row = {
        "tenant_id": user.tenant_id,
        "organization_id": user.organization_id,
        "user_id": user.id,
        **values,
    }
    statement = pg_insert(UserLiveLocation).values(**row)
    # The conflict target is uq_user_live_locations_user. Only the columns the
    # caller actually sent are overwritten, so a fix carrying no speed does not
    # erase the speed of the previous one.
    statement = statement.on_conflict_do_update(
        index_elements=[UserLiveLocation.tenant_id, UserLiveLocation.user_id],
        set_={
            **{key: statement.excluded[key] for key in values},
            "organization_id": statement.excluded.organization_id,
            "received_at": func.now(),
            "updated_at": func.now(),
        },
    ).returning(UserLiveLocation)
    result = await db.execute(statement)
    return result.scalar_one()


async def record_location_ping(db: AsyncSession, *, user: User, values: dict) -> None:
    """Append one fix to the partitioned history."""
    await db.execute(
        pg_insert(UserLocationPing).values(
            tenant_id=user.tenant_id,
            organization_id=user.organization_id,
            user_id=user.id,
            **values,
        )
    )


async def get_live_location(db: AsyncSession, user_id: int) -> UserLiveLocation | None:
    return await db.scalar(select(UserLiveLocation).where(UserLiveLocation.user_id == user_id))


async def list_location_pings(
    db: AsyncSession, user_id: int, *, since: datetime | None = None, limit: int = 100,
) -> list[UserLocationPing]:
    """Most recent fixes first. Bounded by `limit` — this table is unbounded."""
    query = select(UserLocationPing).where(UserLocationPing.user_id == user_id)
    if since is not None:
        query = query.where(UserLocationPing.recorded_at >= since)
    query = query.order_by(UserLocationPing.recorded_at.desc()).limit(limit)
    return list((await db.scalars(query)).all())


# ── Password reset tokens ─────────────────────────────────────────────────────

async def upsert_reset_token(
    db: AsyncSession,
    *,
    email: str,
    token: str,
    reset_type: str,
    code_hash: str | None,
    expires_at: datetime,
    max_attempts: int,
    request_ip: str | None = None,
) -> PasswordResetToken:
    """Create or replace the single active reset row for an email.

    Re-requesting resets the attempt counter (the user gets a fresh code) but
    increments ``sent_count`` so the hourly abuse cap survives.
    """
    now = datetime.now(UTC)
    existing = await db.get(PasswordResetToken, email)
    if existing:
        existing.token = token
        existing.reset_type = reset_type
        existing.code_hash = code_hash
        existing.attempts = 0
        existing.max_attempts = max_attempts
        existing.expires_at = expires_at
        existing.consumed_at = None
        existing.request_ip = request_ip
        existing.sent_count = (existing.sent_count or 0) + 1
        existing.last_sent_at = now
        existing.created_at = existing.created_at or now
        await db.flush()
        return existing

    row = PasswordResetToken(
        email=email,
        token=token,
        reset_type=reset_type,
        code_hash=code_hash,
        expires_at=expires_at,
        max_attempts=max_attempts,
        request_ip=request_ip,
        attempts=0,
        sent_count=1,
        last_sent_at=now,
    )
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


# ── Login OTP challenges ──────────────────────────────────────────────────────

async def upsert_login_otp(
    db: AsyncSession,
    *,
    email: str,
    code_hash: str,
    expires_at: datetime,
    max_attempts: int,
    request_ip: str | None = None,
) -> LoginOtpToken:
    """Create or replace the single active OTP challenge for an email."""
    now = datetime.now(UTC)
    existing = await db.get(LoginOtpToken, email)
    if existing:
        existing.code_hash = code_hash
        existing.attempts = 0
        existing.max_attempts = max_attempts
        existing.expires_at = expires_at
        existing.consumed_at = None
        existing.request_ip = request_ip
        existing.sent_count = (existing.sent_count or 0) + 1
        existing.last_sent_at = now
        existing.created_at = existing.created_at or now
        await db.flush()
        return existing

    row = LoginOtpToken(
        email=email,
        code_hash=code_hash,
        expires_at=expires_at,
        max_attempts=max_attempts,
        request_ip=request_ip,
        attempts=0,
        sent_count=1,
        last_sent_at=now,
    )
    db.add(row)
    await db.flush()
    return row


async def get_login_otp(db: AsyncSession, email: str) -> LoginOtpToken | None:
    return await db.get(LoginOtpToken, email)


async def delete_login_otp(db: AsyncSession, email: str) -> None:
    row = await db.get(LoginOtpToken, email)
    if row:
        await db.delete(row)
        await db.flush()
