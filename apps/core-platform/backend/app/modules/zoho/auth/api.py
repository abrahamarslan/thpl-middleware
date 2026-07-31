from typing import Annotated
from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import RedirectResponse

from app.common.response.schema import ResponseModel
from app.core.conf import settings
from app.modules.users.deps import get_current_user
from app.modules.users.model import User
from app.modules.zoho.auth.service import zoho_auth_service

zoho_auth_router = APIRouter(tags=["zoho-auth"])

async def get_optional_auth_user(request: Request) -> User | None:
    """Conditionally requires authentication based on ZOHO_AUTH_REQUIRE_USER."""
    if settings.ZOHO_AUTH_REQUIRE_USER:
        # We need to manually resolve the dependency if we're wrapping it conditionally,
        # but since FastAPI resolves Depends automatically in the route signature, 
        # it's cleaner to let FastAPI inject it, or we can just make this a standard Depends function.
        pass
    return None

# The easiest way to handle conditional dependencies in FastAPI without breaking the OpenAPI schema
# is to use a dependency that catches AuthError or injects the user optionally.
# But since get_current_user is already written, we can just use a try-except block, 
# or just resolve the header manually.
# A simpler approach: Just make it a standard dependency.
from fastapi.security import HTTPAuthorizationCredentials
from app.common.security.jwt import bearer_scheme
from app.database.db import DBSession

async def get_zoho_auth_user(
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> User | None:
    if not settings.ZOHO_AUTH_REQUIRE_USER:
        return None
    return await get_current_user(db, credentials)

OptionalZohoAuthUser = Annotated[User | None, Depends(get_zoho_auth_user)]


@zoho_auth_router.get("/initiate", response_class=RedirectResponse)
async def initiate_zoho_auth(
    current_user: OptionalZohoAuthUser,
    return_url: str | None = Query(None, description="URL to redirect to after successful authentication"),
) -> RedirectResponse:
    """Generate the Zoho OAuth URL and redirect the user to it."""
    auth_url = await zoho_auth_service.get_authorization_url(return_url)
    return RedirectResponse(url=auth_url)


@zoho_auth_router.get("/callback")
async def zoho_auth_callback(
    request: Request,
    current_user: OptionalZohoAuthUser,
    code: str = Query(..., description="Authorization code from Zoho"),
    state: str = Query(..., description="State parameter for CSRF protection"),
):
    """Handle the OAuth callback from Zoho, exchange code for tokens, and redirect back."""
    user_id = current_user.id if current_user else None
    return_url = await zoho_auth_service.handle_callback(code, state, user_id)
    if return_url:
        return RedirectResponse(url=return_url)
    return ResponseModel(data={"message": "Successfully authenticated with Zoho"})


@zoho_auth_router.post("/revoke", response_model=ResponseModel[dict])
async def revoke_zoho_token(current_user: OptionalZohoAuthUser):
    """Revoke the current Zoho access and refresh tokens."""
    await zoho_auth_service.revoke_token()
    return ResponseModel(data={"message": "Successfully disconnected from Zoho"})
