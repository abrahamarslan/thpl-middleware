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

from fastapi import APIRouter, File, Query, Request, Response, UploadFile

from app.common.client_info import ClientInfoDep
from app.common.exception.errors import ForbiddenError
from app.common.response.schema import PageModel, ResponseModel
from app.common.security.jwt import create_access_token
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.media import service as media_service
from app.modules.media.schema import AvatarOut
from app.modules.organizations.schema import OrganizationOut
from app.modules.rbac.deps import GrantsDep, Perm, org_of
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
    LoginOtpRequest,
    LoginOtpVerifyRequest,
    LoginRequest,
    ModerationOut,
    PasswordPolicyOut,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ThrottleRequest,
    SessionOut,
    SettingsOptionsOut,
    TokenPair,
    UserAdminCreate,
    UserAdminUpdate,
    UserListFilters,
    UserMeOut,
    UserOut,
    UserPublicOut,
    UserSelfUpdate,
    UserSettings,
    UserSettingsUpdate,
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
        client_type=body.client_type,
        installation_id=body.installation_id,
    )
    return ResponseModel(data=tokens)


@auth_router.post("/refresh", response_model=ResponseModel[TokenPair])
async def refresh(db: DBSession, body: RefreshRequest, client: ClientInfoDep):
    return ResponseModel(data=await service.refresh_tokens(db, body.refresh_token, client=client))


@auth_router.post("/logout", response_model=ResponseModel[dict])
async def logout(db: DBSession, user: CurrentUser, client: ClientInfoDep, request: Request):
    """End THIS sign-in session: the token is refused from its next request (401 ``session_revoked``)."""
    revoked = await service.logout(db, user, client=client, claims=getattr(request.state, "token_claims", None))
    return ResponseModel(data={"logged_out": True, "sessions_revoked": revoked})


@auth_router.post("/logout-all", response_model=ResponseModel[dict])
async def logout_all(db: DBSession, user: CurrentUser, client: ClientInfoDep):
    """End EVERY sign-in session of mine (all devices, this one included)."""
    revoked = await service.logout(db, user, client=client, everywhere=True)
    return ResponseModel(data={"logged_out": True, "sessions_revoked": revoked})


@auth_router.get("/sessions", response_model=ResponseModel[list[SessionOut]])
async def my_sessions(db: DBSession, user: CurrentUser, request: Request, include_revoked: bool = False):
    """My sign-in sessions (devices). ``current`` marks the one this request uses."""
    from app.modules.users import sessions

    sid = (getattr(request.state, "token_claims", None) or {}).get("sid")
    rows = await sessions.list_sessions(db, user.id, include_revoked=include_revoked)
    return ResponseModel(data=[SessionOut.model_validate(r).model_copy(update={"current": str(r.uuid) == sid})
                               for r in rows])


@auth_router.delete("/sessions/{session_uuid}", response_model=ResponseModel[dict])
async def end_my_session(db: DBSession, user: CurrentUser, session_uuid: str):
    """Sign one of my devices out."""
    from app.modules.users import sessions

    row = await sessions.get_session(db, session_uuid, user_id=user.id)
    await sessions.revoke(db, row, reason="logout")
    return ResponseModel(data={"revoked": True})


@auth_router.get("/me", response_model=ResponseModel[UserOut])
async def me(db: DBSession, user: CurrentUser):
    return ResponseModel(data=await service.user_out(db, user))


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

# Authorization (docs/rbac-module.md): every route below declares ONE guard — ``Perm(code, target=…)``.
# ``org_of(User)`` judges an action on a user AT THAT USER'S organization, so an administrator of one
# branch cannot touch another branch's people. Reading is two-tier: the directory (id, name, avatar) is
# open to anyone with ``users.directory:read``; the full record (medical history, PAN, bank details …)
# needs ``users.user:read`` — or is your own.
_USER = org_of("app.modules.users.model:User", param="user_id")


@users_router.get("", response_model=ResponseModel[PageModel[UserOut | UserPublicOut]])
async def list_users(
    db: DBSession, viewer: Perm("users.directory:read"), grants: GrantsDep, filters: UserListFilters = Query(),
):
    users, total = await service.list_users(db, filters)
    full = grants.can_anywhere("users.user:read")          # SHAPE only; the gate above already ran
    return ResponseModel(
        data=PageModel(
            items=await (service.user_outs(db, users) if full
                         else service.user_public_outs(db, users, viewer=viewer)),
            page=filters.page,
            page_size=filters.page_size,
            total=total,
            has_more=filters.page * filters.page_size < total,
        )
    )


@users_router.post("", response_model=ResponseModel[UserOut], status_code=201)
async def create_user(db: DBSession, current: Perm("users.user:create"), body: UserAdminCreate):
    """Create a user. They start as a ``member``; give them a role with PUT /users/{id}/base-role."""
    user = await service.create_user(db, body, created_by=current.id, actor_label=current.email)
    return ResponseModel(data=await service.user_out(db, user))


@users_router.get("/{user_id}", response_model=ResponseModel[UserOut | UserPublicOut])
async def get_user(
    db: DBSession, viewer: Perm("users.directory:read", target=_USER), grants: GrantsDep, user_id: int,
    include_deleted: bool = Query(False, description="Also match soft-deleted users"),
):
    user = await service.get_user(db, user_id, include_deleted=include_deleted)
    if user.id == viewer.id or grants.can_anywhere("users.user:read"):
        return ResponseModel(data=await service.user_out(db, user))
    return ResponseModel(data=(await service.user_public_outs(db, [user], viewer=viewer))[0])


@users_router.put("/{user_id}", response_model=ResponseModel[UserOut])
async def update_user(
    db: DBSession, current: Perm("users.user:update", target=_USER), user_id: int, body: UserAdminUpdate,
    client: ClientInfoDep,
):
    user = await service.update_user(
        db, user_id, body, updated_by=current.id, actor_label=current.email, client=client
    )
    return ResponseModel(data=await service.user_out(db, user))


@users_router.delete("/{user_id}", response_model=ResponseModel[dict])
async def delete_user(
    db: DBSession, current: Perm("users.user:delete", target=_USER), user_id: int,
    hard: bool = Query(False, description="Permanently delete instead of soft delete"),
):
    await service.delete_user(
        db, user_id, deleted_by=current.id, hard=hard, actor_label=current.email
    )
    return ResponseModel(data={"deleted": True, "hard": hard})


@users_router.post("/{user_id}/restore", response_model=ResponseModel[UserOut])
async def restore_user(db: DBSession, _: Perm("users.user:restore", target=_USER), user_id: int):
    user = await service.restore_user(db, user_id)
    return ResponseModel(data=await service.user_out(db, user))


# ── Moderation: ban / unban / throttle ───────────────────────────────────────

@users_router.get("/{user_id}/sessions", response_model=ResponseModel[list[SessionOut]])
async def user_sessions(db: DBSession, _: Perm("users.session:read", target=_USER), user_id: int,
                        include_revoked: bool = False):
    """A user's sign-in sessions (devices)."""
    from app.modules.users import sessions

    await service.get_user(db, user_id)
    return ResponseModel(data=[SessionOut.model_validate(r) for r in
                               await sessions.list_sessions(db, user_id, include_revoked=include_revoked)])


@users_router.delete("/{user_id}/sessions/{session_uuid}", response_model=ResponseModel[dict])
async def end_user_session(db: DBSession, _: Perm("users.session:delete", target=_USER), user_id: int,
                           session_uuid: str):
    """Sign a user's device out (reason ``admin``)."""
    from app.modules.users import sessions

    row = await sessions.get_session(db, session_uuid, user_id=user_id)
    await sessions.revoke(db, row, reason="admin")
    return ResponseModel(data={"revoked": True})


@users_router.delete("/{user_id}/sessions", response_model=ResponseModel[dict])
async def end_user_sessions(db: DBSession, _: Perm("users.session:delete", target=_USER), user_id: int):
    """Sign a user out of every device."""
    from app.modules.users import sessions

    await service.get_user(db, user_id)
    return ResponseModel(data={"revoked": await sessions.revoke_all(db, user_id, reason="admin")})


@users_router.get("/{user_id}/moderation", response_model=ResponseModel[ModerationOut])
async def get_moderation(db: DBSession, _: Perm("users.moderation:manage", target=_USER), user_id: int):
    """Current ban/throttle/lock state of a user."""
    user = await service.get_user(db, user_id, include_deleted=True)
    return ResponseModel(data=ModerationOut(**moderation.moderation_state(user)))


@users_router.post("/{user_id}/ban", response_model=ResponseModel[UserOut])
async def ban_user(
    db: DBSession, current: Perm("users.moderation:manage", target=_USER), user_id: int, body: BanRequest,
):
    """Ban a user (permanent unless `until` is given); mirrors to Authentik."""
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.ban_user(db, user, reason=body.reason, until=body.until, actor_id=current.id)
    return ResponseModel(data=await service.user_out(db, user))


@users_router.post("/{user_id}/unban", response_model=ResponseModel[UserOut])
async def unban_user(db: DBSession, current: Perm("users.moderation:manage", target=_USER), user_id: int):
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.unban_user(db, user, actor_id=current.id)
    return ResponseModel(data=await service.user_out(db, user))


@users_router.post("/{user_id}/throttle", response_model=ResponseModel[UserOut])
async def throttle_user(
    db: DBSession, current: Perm("users.moderation:manage", target=_USER), user_id: int, body: ThrottleRequest,
):
    """Throttle a user: existing session stays, new auth attempts are 429'd."""
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.throttle_user(
        db, user, reason=body.reason, until=body.until, actor_id=current.id
    )
    return ResponseModel(data=await service.user_out(db, user))


@users_router.post("/{user_id}/unthrottle", response_model=ResponseModel[UserOut])
async def unthrottle_user(db: DBSession, current: Perm("users.moderation:manage", target=_USER), user_id: int):
    user = await service.get_user(db, user_id, include_deleted=True)
    user = await moderation.unthrottle_user(db, user, actor_id=current.id)
    return ResponseModel(data=await service.user_out(db, user))


# ════════════════════════════════ ME / PROFILE ═══════════════════════════════

@me_router.get("/profile", response_model=ResponseModel[UserMeOut])
@auth_router.get("/me/profile", response_model=ResponseModel[UserMeOut])
async def get_my_profile(db: DBSession, user: CurrentUser):
    """The authenticated user's full self view.

    This is ``GET /api/auth/me`` plus the localization source and the primary
    address — the address is a ``geo.place_links`` row, not a users column.
    """
    data = await service.get_my_profile_view(db, user)
    return ResponseModel.ok(data=data, module="users", msg_key="profile_fetched")


@me_router.patch("/profile", response_model=ResponseModel[UserMeOut])
@auth_router.patch("/me/profile", response_model=ResponseModel[UserMeOut])
async def update_my_profile(
    db: DBSession, user: CurrentUser, body: UserSelfUpdate, client: ClientInfoDep,
):
    """Update the authenticated user's own profile.

    Accepts an explicit allowlist of personal/preference fields (never
    ``role_id``/``status``/... — those are admin-only) plus an optional
    ``address`` that is written through the location hub. ``email`` and
    ``username`` are read-only here: changing them is a login/verification flow,
    not a profile edit.
    """
    data = await service.update_my_profile(db, user, body, client=client)
    return ResponseModel.ok(data=data, module="users", msg_key="profile_updated")


# ══════════════════════════════ ME / APP SETTINGS ═════════════════════════════
# App-specific preferences (profile visibility, theme, notification channels)
# persisted in `users.application_settings` JSONB. GET returns the full effective
# settings; PATCH deep-merges any subset, so an app can send one changed toggle.

@me_router.get("/settings/options", response_model=ResponseModel[SettingsOptionsOut])
@auth_router.get("/me/settings/options", response_model=ResponseModel[SettingsOptionsOut])
async def settings_options(_: CurrentUser):
    """Every allowed settings value with its label — map by ``value``. ``profile_visibility``: everyone
    (every user of your organization's tenant) · team · managers · private; ``contact_visibility``:
    everyone · team · hidden. Administrators always see profiles (``admin_override``)."""
    return ResponseModel(data=service.settings_options())


@me_router.get("/settings", response_model=ResponseModel[UserSettings])
@auth_router.get("/me/settings", response_model=ResponseModel[UserSettings])
async def get_my_settings(db: DBSession, user: CurrentUser):
    """The authenticated user's effective app settings (defaults where unset)."""
    return ResponseModel.ok(
        data=await service.get_my_settings(db, user), module="users", msg_key="settings_fetched",
    )


@me_router.patch("/settings", response_model=ResponseModel[UserSettings])
@auth_router.patch("/me/settings", response_model=ResponseModel[UserSettings])
async def update_my_settings(
    db: DBSession, user: CurrentUser, body: UserSettingsUpdate, client: ClientInfoDep,
):
    """Update the authenticated user's app settings.

    Any subset of the settings may be sent — sections and fields merge over the
    stored values, so a client only sends what changed.
    """
    data = await service.update_my_settings(db, user, body, client=client)
    return ResponseModel.ok(data=data, module="users", msg_key="settings_updated")


# ════════════════════════════════ ME / AVATAR ════════════════════════════════
# Public media: the returned URLs are served by the unauthenticated
# /public/m router (modules/media/public_api.py), so other applications can embed
# them with a plain GET. Variants are generated asynchronously — 202, then poll
# GET /api/me/profile until `avatar_urls` has no nulls.

@me_router.post("/avatar", response_model=ResponseModel[AvatarOut], status_code=202)
async def upload_my_avatar(db: DBSession, user: CurrentUser, file: UploadFile = File(...)):
    """Set (or replace) the authenticated user's avatar (PNG / JPEG / WebP, max 10 MB, max 40 MP).

    The image is validated and re-encoded with all EXIF/GPS metadata removed.
    Replacing an avatar issues a NEW media id (and so new URLs); the previous
    image is soft-deleted and its bytes purged after a 24 h grace window.
    """
    media = await media_service.replace_avatar(db, user_id=user.id, upload=file)
    return ResponseModel(
        data=AvatarOut(media_id=media.uuid, status=media.status, avatar_urls=media_service.media_urls(media)),
        msg="Avatar uploaded; conversions queued",
    )


@me_router.delete("/avatar", status_code=204)
async def delete_my_avatar(db: DBSession, user: CurrentUser):
    """Remove the authenticated user's avatar (idempotent)."""
    await media_service.delete_avatar(db, user_id=user.id)
    return Response(status_code=204)


# ════════════════════════════════ ME / ORGANIZATION ══════════════════════════
# Login returns tokens only and `/me` carries no organization, so a signed-in
# client otherwise has no way to learn the code it must send as
# `X-Organization-Code`. This returns the organization the user BELONGS to —
# never the branch an `X-Organization-*` header selects for the request.

@me_router.get("/organization", response_model=ResponseModel[OrganizationOut])
@auth_router.get("/me/organization", response_model=ResponseModel[OrganizationOut])
async def get_my_organization(db: DBSession, user: CurrentUser):
    """The authenticated user's own organization.

    The ``org_code`` here is what a client sends back as ``X-Organization-Code``
    on subsequent calls; the rest of the profile (legal name, type, status,
    locale, address) is included for display. Both organization headers remain
    optional throughout the API.
    """
    org = await service.get_my_organization(db, user)
    return ResponseModel.ok(
        data=OrganizationOut.model_validate(org), module="users", msg_key="organization_fetched",
    )


# ════════════════════════════════ ME / LOCATION ══════════════════════════════
# `PATCH/GET /api/me/location` moved to app/modules/fieldops/api_me.py (one-item batches into the
# field-ops stream). The user's position lives in `user_live_locations` (last known) and
# `fieldops.location_pings` (history),
# not on the users row. Addresses are NOT here: they go through the platform-wide
# address book at `/api/addresses` with `owner_type=user` — one address API for
# every entity, not one per module.

@users_router.get("/{user_id}/location", response_model=ResponseModel[LiveLocationOut | None])
async def get_user_location(db: DBSession, _: Perm("users.location:read", target=_USER), user_id: int):
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
