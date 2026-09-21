from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials

from app.common.response.schema import ResponseModel
from app.common.security.jwt import bearer_scheme
from app.core.conf import settings
from app.database.db import DBSession
from app.modules.users.deps import get_current_user
from app.modules.users.model import User
from app.modules.zoho.auth.schema import (
    OAuthCallbackOut,
    OAuthInitiateOut,
    OAuthRevokeOut,
    OAuthStatusOut,
)
from app.modules.zoho.auth.service import ZohoConsentError, zoho_auth_service
from app.modules.zoho.core.auth import zoho_token_manager

zoho_auth_router = APIRouter(tags=["zoho-auth"])


async def get_zoho_auth_user(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User | None:
    if not settings.ZOHO_AUTH_REQUIRE_USER:
        return None
    return await get_current_user(db, credentials)

OptionalZohoAuthUser = Annotated[User | None, Depends(get_zoho_auth_user)]


async def get_optional_callback_user(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User | None:
    """/callback is reached via a browser redirect from Zoho, which cannot send
    an Authorization header. By default it is JWT-free (identity/provenance is
    verified via the CSRF `state` in Redis). Opt into a token only if the
    callback is invoked from a client that can actually attach one."""
    if not settings.ZOHO_CALLBACK_REQUIRE_USER:
        return None
    return await get_current_user(db, credentials)

OptionalZohoCallbackUser = Annotated[User | None, Depends(get_optional_callback_user)]


@zoho_auth_router.get("/initiate")
async def initiate_zoho_auth(
    current_user: OptionalZohoAuthUser,
    return_url: str | None = Query(
        None,
        description="Where the browser lands AFTER connecting (a frontend page or path). Leave empty to use "
                    "ZOHO_AUTH_RETURN_URL, or to get a JSON result. NOT the Zoho callback URL.",
    ),
    redirect: bool = Query(True, description="Whether to redirect immediately (browser) or return JSON (SPA/API)"),
):
    """Generate the Zoho OAuth URL and redirect the user or return the URL.

    From Swagger: call with ``redirect=false``, open the returned
    ``authorization_url`` in a browser tab and consent. Zoho sends the browser
    to ZOHO_REDIRECT_URL (/callback), which stores the token and then shows
    ``{"connected": true}`` or redirects to ``return_url``.
    """
    auth_url = await zoho_auth_service.get_authorization_url(return_url)
    if redirect:
        return RedirectResponse(url=auth_url)
    return ResponseModel.ok(
        data={"authorization_url": auth_url},
        module="zoho.auth",
        msg_key="auth_initiated",
    )


@zoho_auth_router.get("/callback")
async def zoho_auth_callback(
    request: Request,
    db: DBSession,
    current_user: OptionalZohoCallbackUser,
    code: str | None = Query(None, description="Authorization code from Zoho"),
    state: str | None = Query(None, description="State parameter for CSRF protection"),
    error: str | None = Query(None, description="Set by Zoho when consent failed (e.g. access_denied)"),
):
    """Handle the OAuth callback from Zoho, exchange code for tokens, and redirect back.

    Only Zoho's redirect should reach this URL. Without ``code``/``state`` it
    answers with an explanation instead of a bare validation error.
    """
    if error:
        raise ZohoConsentError(f"Zoho did not grant access: {error}", data={"zoho_error": error})
    if not code or not state:
        raise ZohoConsentError(
            "This is Zoho's OAuth callback and needs the code/state Zoho appends. Start the flow at "
            "/api/zoho/auth/initiate; if you got here after connecting, the connection already succeeded "
            "(check /api/zoho/auth/status)."
        )
    user_id = current_user.id if current_user else None
    return_url = await zoho_auth_service.handle_callback(db, code, state, user_id)
    if return_url:
        return RedirectResponse(url=return_url)
    return ResponseModel.ok(data={"connected": True, "persisted": True}, module="zoho.auth",
                            msg_key="auth_connected")


@zoho_auth_router.post("/revoke", response_model=ResponseModel[OAuthRevokeOut])
async def revoke_zoho_token(db: DBSession, current_user: OptionalZohoAuthUser):
    """Revoke the current Zoho access and refresh tokens."""
    actor_id = current_user.id if current_user else None
    await zoho_auth_service.revoke_token(db, actor_id=actor_id)
    return ResponseModel.ok(data={"disconnected": True}, module="zoho.auth", msg_key="auth_disconnected")


@zoho_auth_router.get("/connection", response_model=ResponseModel[dict])
async def zoho_connection(
    current_user: OptionalZohoAuthUser,
    probe: str = Query("auto", pattern="^(auto|always|never)$",
                       description="auto: one live call only when there is no recent evidence; "
                                   "always: force it (cached 60 s); never: local checks only"),
):
    """Can Zoho syncs run right now — and if not, why? (docs/zoho-sync-implementation/auth.md §5c)

    Checks configuration, the stored credential, the access token, the engine
    switches, today's quota, the circuit breakers and the last real Zoho calls;
    makes at most ONE org-scoped live call (``GET /organizations/{id}``).
    """
    from app.modules.zoho.core.connection import connection_report

    report = await connection_report(probe=probe)  # type: ignore[arg-type]
    return ResponseModel.ok(data=report, msg=report["summary"])


@zoho_auth_router.get("/status", response_model=ResponseModel[OAuthStatusOut])
async def get_zoho_auth_status(current_user: OptionalZohoAuthUser):
    """Check whether Zoho integration is active and has valid tokens."""
    refresh_token = await zoho_token_manager.get_refresh_token()
    is_connected = bool(refresh_token)
    msg_key = "status_connected" if is_connected else "status_disconnected"
    return ResponseModel.ok(
        data={"is_connected": is_connected},
        module="zoho.auth",
        msg_key=msg_key,
    )
