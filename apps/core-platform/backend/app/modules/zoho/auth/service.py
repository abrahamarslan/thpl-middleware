import json
import uuid
import httpx
import structlog
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exception.errors import AuthError
from app.core.conf import settings
from app.database.redis import redis_client
from app.modules.activity.recorder import record_activity
from app.modules.zoho.core.token_manager import zoho_token_manager
from app.modules.zoho.core.exceptions import ZohoAuthError

logger = structlog.get_logger("app.zoho.auth")

STATE_KEY_PREFIX = "zoho:oauth:state:"
STATE_TTL = 600  # 10 minutes


class ZohoAuthService:
    async def get_authorization_url(self, return_url: str | None = None) -> str:
        """Generate the Zoho OAuth URL and persist state to Redis."""
        state = uuid.uuid4().hex
        
        state_data = {
            "return_url": return_url or settings.ZOHO_REDIRECT_URL
        }
        
        await redis_client.set(
            f"{STATE_KEY_PREFIX}{state}", 
            json.dumps(state_data), 
            ex=STATE_TTL
        )
        
        params = {
            "client_id": settings.ZOHO_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": settings.ZOHO_REDIRECT_URL,
            "scope": settings.ZOHO_SCOPE,
            "access_type": settings.ZOHO_ACCESS_TYPE,
            "prompt": settings.ZOHO_PROMPT,
            "state": state
        }
        
        auth_url = f"{settings.ZOHO_OAUTH_URL}?{urlencode(params)}"
        logger.info("zoho_oauth_initiated", state=state, return_url=return_url)
        return auth_url

    async def handle_callback(
        self, db: AsyncSession, code: str, state: str, user_id: int | None = None
    ) -> str:
        """Validate state, exchange code for tokens, and return the original return_url."""
        state_key = f"{STATE_KEY_PREFIX}{state}"
        state_data_raw = await redis_client.get(state_key)

        if not state_data_raw:
            # A missing/expired state is a client error (failed CSRF check),
            # not an upstream Zoho failure — surface it as 401, not 502.
            raise AuthError("Invalid or expired OAuth state parameter (CSRF protection)")
            
        state_data = json.loads(state_data_raw)
        return_url = state_data.get("return_url")
        
        # Burn the state token so it can't be reused
        await redis_client.delete(state_key)
        
        logger.info("zoho_oauth_callback_started", code_length=len(code))
        
        async with httpx.AsyncClient(timeout=settings.ZOHO_TIMEOUT_SECONDS) as http:
            resp = await http.post(
                settings.ZOHO_ACCESS_TOKEN_URL,
                params={
                    "grant_type": "authorization_code",
                    "client_id": settings.ZOHO_CLIENT_ID,
                    "client_secret": settings.ZOHO_CLIENT_SECRET,
                    "redirect_uri": settings.ZOHO_REDIRECT_URL,
                    "code": code,
                },
            )
            
        if resp.status_code != 200:
            logger.error("zoho_oauth_callback_failed", status=resp.status_code, body=resp.text[:500])
            raise ZohoAuthError(
                "Failed to exchange authorization code for Zoho tokens",
                http_status=resp.status_code,
            )
            
        payload = resp.json()
        
        if "error" in payload:
            raise ZohoAuthError(f"Zoho token exchange error: {payload['error']}")
            
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        expires_in = int(payload.get("expires_in", 3600))
        
        if not access_token:
            raise ZohoAuthError("No access token found in Zoho response")
            
        await zoho_token_manager.store_tokens(access_token, refresh_token, expires_in)
        
        logger.info("zoho_oauth_callback_success", expires_in=expires_in)

        # Credential-changing action — persisted to activity_logs for audit.
        await record_activity(
            db,
            action="zoho_auth_connected",
            actor_id=user_id,
            subject_type="ZohoIntegration",
            subject_id="global",
            description="Connected the Zoho account (OAuth callback)",
            context={"expires_in": expires_in, "refresh_token_rotated": bool(refresh_token)},
        )
        
        return return_url or settings.ZOHO_REDIRECT_URL

    async def revoke_token(self, db: AsyncSession, *, actor_id: int | None = None) -> None:
        """Revoke the current Zoho token."""
        refresh_token = await zoho_token_manager.get_refresh_token()
        
        if not refresh_token:
            raise ZohoAuthError("No Zoho refresh token available to revoke")
            
        logger.info("zoho_oauth_revoke_started")
        
        async with httpx.AsyncClient(timeout=settings.ZOHO_TIMEOUT_SECONDS) as http:
            resp = await http.post(
                f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token/revoke",
                params={
                    "token": refresh_token,
                },
            )
            
        if resp.status_code != 200:
            logger.error("zoho_oauth_revoke_failed", status=resp.status_code, body=resp.text[:500])
            # Even if it fails on Zoho's side, we should clear our local cache
            
        await zoho_token_manager.clear_tokens()

        # Credential-changing action — persisted to activity_logs for audit.
        await record_activity(
            db,
            action="zoho_auth_revoked",
            actor_id=actor_id,
            subject_type="ZohoIntegration",
            subject_id="global",
            description="Revoked the Zoho connection",
            context={"zoho_revoke_status": resp.status_code},
        )
        logger.info("zoho_oauth_revoke_success")

zoho_auth_service = ZohoAuthService()
