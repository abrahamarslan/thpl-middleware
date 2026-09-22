"""Users module — HTTP endpoints (api layer).

Two routers:
  auth_router  -> /api/auth/*   register, login, login-otp/request|verify,
                                refresh, me, change-password, password-policy,
                                forgot-password, reset-password, dev-token
  users_router -> /api/users/*  list, get, create, update, soft/hard delete, restore

Every auth entry point resolves request audit context (IP/device/GeoIP) via
ClientInfoDep; see docs/modules/auth-module-documentation.md.
"""

from dataclasses import asdict

from fastapi import APIRouter, Query

from app.common.client_info import ClientInfoDep
from app.common.exception.errors import ForbiddenError
from app.common.response.schema import PageModel, ResponseModel
from app.common.security.jwt import create_access_token
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users import login_otp, moderation, service
from app.modules.users.deps import CurrentUser, OrganizationCode
from app.modules.users.password_policy import get_password_policy
from app.modules.users.schema import (
    BanRequest,
    ChangePasswordRequest,
    CountryOut,
    CountryTimezoneOut,
    ForgotPasswordOut,
    ForgotPasswordRequest,
    LiveLocationOut,
    LocationUpdate,
    LoginOtpRequest,
    LoginOtpVerifyRequest,
    LoginRequest,
    ModerationOut,
    PasswordPolicyOut,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ThrottleRequest,
    TokenPair,
    UserCreate,
    UserListFilters,
    UserOut,
    UserProfileOut,
    UserProfileUpdate,
    UserUpdate,
)

auth_router = APIRouter()
users_router = APIRouter()
countries_router = APIRouter()
me_router = APIRouter()


# ════════════════════════════════ AUTH ════════════════════════════════════════

@auth_router.post("/register", response_model=ResponseModel[UserOut], status_code=201)
async def register(
    db: DBSession, body: RegisterRequest, client: ClientInfoDep, org_code: OrganizationCode = None,
):
    """Create an account.

    Registration is unauthenticated, so the organization comes from
    `X-Organization-Code` or — when it is omitted — the deployment's configured
    default (`DEFAULT_ORGANIZATION_CODE` in `DEFAULT_TENANT_CODE`). With neither,
    the request is refused with `organization_required` rather than guessed.
    """
    user = await service.register(db, body, client=client, org_code=org_code)
    return ResponseModel.ok(
        data=UserOut.model_validate(user),
        module="users",
        msg_key="register_success",
    )


@auth_router.post("/login", response_model=ResponseModel[TokenPair])
async def login(db: DBSession, body: LoginRequest, client: ClientInfoDep):
    _, tokens = await service.login(db, body, client=client)
    return ResponseModel(data=tokens)


@auth_router.post("/login-otp/request", response_model=ResponseModel[dict])
async def login_otp_request(db: DBSession, body: LoginOtpRequest, client: ClientInfoDep):
    """Send a one-time sign-in code to the account's email on file."""
    result = await login_otp.request_login_otp(db, identifier=body.identifier, client=client)
    payload: dict = {"sent": result.sent, "expires_at": result.expires_at}
    if settings.DEBUG:
        payload["debug_code"] = result.debug_code
    return ResponseModel(data=payload)


@auth_router.post("/login-otp/verify", response_model=ResponseModel[TokenPair])
async def login_otp_verify(db: DBSession, body: LoginOtpVerifyRequest, client: ClientInfoDep):
    """Exchange a valid one-time code for a token pair (passwordless login)."""
    _, tokens = await login_otp.verify_login_otp(
        db,
        identifier=body.identifier,
        code=body.code,
        device_id=body.device_id,
        device_type=body.device_type,
        client=client,
    )
    return ResponseModel(data=tokens)


@auth_router.post("/refresh", response_model=ResponseModel[TokenPair])
async def refresh(db: DBSession, body: RefreshRequest, client: ClientInfoDep):
    return ResponseModel(data=await service.refresh_tokens(db, body.refresh_token, client=client))


@auth_router.post("/logout", response_model=ResponseModel[dict])
async def logout(db: DBSession, user: CurrentUser, client: ClientInfoDep):
    await service.logout(db, user, client=client)
    return ResponseModel(data={"logged_out": True})


@auth_router.get("/me", response_model=ResponseModel[UserOut])
async def me(user: CurrentUser):
    return ResponseModel(data=UserOut.model_validate(user))


@auth_router.post("/change-password", response_model=ResponseModel[dict])
async def change_password(db: DBSession, user: CurrentUser, body: ChangePasswordRequest, client: ClientInfoDep):
    """Change the **authenticated** user's password.

    The account is identified by the bearer token (`Authorization: Bearer
    <access_token>`, resolved to `CurrentUser`) — the body intentionally carries
    only `current_password` + `new_password`.
    """
    await service.change_password(
        db, user, current_password=body.current_password, new_password=body.new_password, client=client
    )
    return ResponseModel(data={"changed": True})


@auth_router.get("/password-policy", response_model=ResponseModel[PasswordPolicyOut])
async def password_policy():
    """Public: the active rules so clients can pre-validate and show hints."""
    return ResponseModel(data=PasswordPolicyOut(**asdict(get_password_policy())))


@auth_router.post("/forgot-password", response_model=ResponseModel[ForgotPasswordOut])
async def forgot_password(db: DBSession, body: ForgotPasswordRequest, client: ClientInfoDep):
    result = await service.request_password_reset(
        db, identifier=body.identifier, reset_type=body.reset_type, client=client
    )
    return ResponseModel.ok(data=result, module="users", msg_key="password_reset_sent")


@auth_router.post("/reset-password", response_model=ResponseModel[dict])
async def reset_password(db: DBSession, body: ResetPasswordRequest, client: ClientInfoDep):
    await service.reset_password(
        db,
        identifier=body.identifier,
        token_or_code=body.token_or_code,
        new_password=body.new_password,
        client=client,
    )
    return ResponseModel(data={"reset": True})


@auth_router.post("/dev-token", response_model=ResponseModel[dict], include_in_schema=False)
async def dev_token(db: DBSession):
    """DEBUG-only token mint for local API testing.

    Gets-or-creates a real `dev@local.test` user row so the token works
    against every CurrentUser-protected endpoint (the subject must be a
    numeric user id — a synthetic subject 500s at token use, not mint).
    """
    if not settings.DEBUG:
        raise ForbiddenError("dev-token is only available when DEBUG=true")
    user = await service.get_or_create_dev_user(db)
    return ResponseModel(
        data={"access_token": create_access_token(str(user.id), claims={"scope": "dev"})}
    )


# ════════════════════════════════ USERS ═══════════════════════════════════════

@users_router.get("", response_model=ResponseModel[PageModel[UserOut]])
async def list_users(db: DBSession, _: CurrentUser, filters: UserListFilters = Query()):
    users, total = await service.list_users(db, filters)
    return ResponseModel(
        data=PageModel(
            items=[UserOut.model_validate(u) for u in users],
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@users_router.post("", response_model=ResponseModel[UserOut], status_code=201)
async def create_user(db: DBSession, current: CurrentUser, body: UserCreate):
    user = await service.create_user(db, body, created_by=current.id, actor_label=current.email)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.get("/{user_id}", response_model=ResponseModel[UserOut])
async def get_user(
    db: DBSession, _: CurrentUser, user_id: int,
    include_deleted: bool = Query(False, description="Also match soft-deleted users"),
):
    user = await service.get_user(db, user_id, include_deleted=include_deleted)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.put("/{user_id}", response_model=ResponseModel[UserOut])
async def update_user(
    db: DBSession, current: CurrentUser, user_id: int, body: UserUpdate, client: ClientInfoDep
):
    user = await service.update_user(
        db, user_id, body, updated_by=current.id, actor_label=current.email, client=client
    )
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.delete("/{user_id}", response_model=ResponseModel[dict])
async def delete_user(
    db: DBSession, current: CurrentUser, user_id: int,
    hard: bool = Query(False, description="Permanently delete instead of soft delete"),
):
    await service.delete_user(
        db, user_id, deleted_by=current.id, hard=hard, actor_label=current.email
    )
    return ResponseModel(data={"deleted": True, "hard": hard})


@users_router.post("/{user_id}/restore", response_model=ResponseModel[UserOut])
async def restore_user(db: DBSession, _: CurrentUser, user_id: int):
    user = await service.restore_user(db, user_id)
    return ResponseModel(data=UserOut.model_validate(user))


# ── Moderation: ban / unban / throttle ───────────────────────────────────────

@users_router.get("/{user_id}/moderation", response_model=ResponseModel[ModerationOut])
async def get_moderation(db: DBSession, _: CurrentUser, user_id: int):
    """Current ban/throttle/lock state of a user."""
    user = await service.get_user(db, user_id, include_deleted=True)
    return ResponseModel(data=ModerationOut(**moderation.moderation_state(user)))


@users_router.post("/{user_id}/ban", response_model=ResponseModel[UserOut])
async def ban_user(db: DBSession, current: CurrentUser, user_id: int, body: BanRequest):
    """Ban a user (permanent unless `until` is given); mirrors to Authentik."""
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.ban_user(db, user, reason=body.reason, until=body.until, actor_id=current.id)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.post("/{user_id}/unban", response_model=ResponseModel[UserOut])
async def unban_user(db: DBSession, current: CurrentUser, user_id: int):
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.unban_user(db, user, actor_id=current.id)
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.post("/{user_id}/throttle", response_model=ResponseModel[UserOut])
async def throttle_user(db: DBSession, current: CurrentUser, user_id: int, body: ThrottleRequest):
    """Throttle a user: existing session stays, new auth attempts are 429'd."""
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.throttle_user(
        db, user, reason=body.reason, until=body.until, actor_id=current.id
    )
    return ResponseModel(data=UserOut.model_validate(user))


@users_router.post("/{user_id}/unthrottle", response_model=ResponseModel[UserOut])
async def unthrottle_user(db: DBSession, current: CurrentUser, user_id: int):
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.unthrottle_user(db, user, actor_id=current.id)
    return ResponseModel(data=UserOut.model_validate(user))


# ════════════════════════════════ ME / PROFILE ═══════════════════════════════

@me_router.get("/profile", response_model=ResponseModel[UserProfileOut])
@auth_router.get("/me/profile", response_model=ResponseModel[UserProfileOut])
async def get_my_profile(db: DBSession, user: CurrentUser):
    """Retrieve the authenticated user's localization profile."""
    profile = await service.get_or_create_profile(db, user.id)
    return ResponseModel.ok(
        data=UserProfileOut.model_validate(profile),
        module="users",
        msg_key="profile_fetched",
    )


@me_router.patch("/profile", response_model=ResponseModel[UserProfileOut])
@auth_router.patch("/me/profile", response_model=ResponseModel[UserProfileOut])
async def update_my_profile(db: DBSession, user: CurrentUser, body: UserProfileUpdate):
    """Update user country (auto-timezone) and/or timezone (locks source to 'manual')."""
    profile = await service.update_user_profile(db, user, body)
    return ResponseModel.ok(
        data=UserProfileOut.model_validate(profile),
        module="users",
        msg_key="profile_updated",
    )


# ════════════════════════════════ ME / LOCATION ══════════════════════════════
# The user's position lives in `user_live_locations` / `user_location_pings`,
# not on the users row. Addresses are NOT here: they go through the platform-wide
# address book at `/api/addresses` with `owner_type=user` — one address API for
# every entity, not one per module.

@me_router.patch("/location", response_model=ResponseModel[LiveLocationOut])
@auth_router.patch("/me/location", response_model=ResponseModel[LiveLocationOut])
async def update_my_location(
    db: DBSession, user: CurrentUser, body: LocationUpdate, client: ClientInfoDep
):
    """Report the authenticated user's current position (one fix).

    Called on every GPS update from FSA/DLP, so it writes only the telemetry
    tables — never the `users` master row that authentication reads.
    """
    live = await service.record_location(db, user, body, client=client)
    return ResponseModel.ok(
        data=LiveLocationOut.from_row(live), module="users", msg_key="location_recorded",
    )


@me_router.get("/location", response_model=ResponseModel[LiveLocationOut | None])
@auth_router.get("/me/location", response_model=ResponseModel[LiveLocationOut | None])
async def get_my_location(db: DBSession, user: CurrentUser):
    """The authenticated user's last known position (`null` if never reported)."""
    live = await service.get_live_location(db, user.id)
    return ResponseModel(data=LiveLocationOut.from_row(live) if live else None)


@users_router.get("/{user_id}/location", response_model=ResponseModel[LiveLocationOut | None])
async def get_user_location(db: DBSession, _: CurrentUser, user_id: int):
    """A user's last known position — what dispatch and beat planning read."""
    await service.get_user(db, user_id)          # 404 for an unknown/other-tenant user
    live = await service.get_live_location(db, user_id)
    return ResponseModel(data=LiveLocationOut.from_row(live) if live else None)


# ════════════════════════════════ COUNTRIES & TIMEZONES ══════════════════════

@countries_router.get("", response_model=ResponseModel[list[CountryOut]])
async def list_countries(db: DBSession):
    """List all active ISO 3166-1 countries (cached)."""
    countries = await service.get_cached_countries(db)
    return ResponseModel.ok(
        data=[CountryOut(**c) for c in countries],
        module="users",
        msg_key="countries_fetched",
    )


@countries_router.get("/{iso2}/timezones", response_model=ResponseModel[list[CountryTimezoneOut]])
async def list_country_timezones(db: DBSession, iso2: str):
    """List all IANA timezones mapped to a country (cached)."""
    timezones = await service.get_cached_country_timezones(db, iso2)
    return ResponseModel.ok(
        data=[CountryTimezoneOut(**tz) for tz in timezones],
        module="users",
        msg_key="timezones_fetched",
    )
