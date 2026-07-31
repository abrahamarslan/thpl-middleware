"""Authentik OIDC token validation (RS256 via JWKS).

Authentik is the identity provider; the application keeps its OWN users
table as the profile store. This module only validates Authentik-issued
JWTs; JIT provisioning into the users table happens in
app/modules/users/service.py (provision_from_authentik).

Setup in Authentik (once):
  1. Create an OAuth2/OIDC Provider + Application (slug: core-platform).
  2. Set AUTHENTIK_ISSUER to the provider's issuer URL, e.g.
       https://auth.app.local/application/o/core-platform/
  3. Set AUTHENTIK_AUDIENCE to the provider's client_id.
  4. Set AUTHENTIK_ENABLED=true.
"""

import asyncio
from typing import Any

import jwt
import structlog

from app.common.exception.errors import AuthError
from app.core.conf import settings

logger = structlog.get_logger("app.security.authentik")

_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = settings.AUTHENTIK_JWKS_URL or f"{settings.AUTHENTIK_ISSUER.rstrip('/')}/jwks/"
        # PyJWKClient caches signing keys in-process for `lifespan` seconds
        _jwks_client = jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks_client


def looks_like_authentik_token(token: str) -> bool:
    """Cheap pre-check: first-party tokens are HS256, Authentik's are RS256."""
    try:
        header = jwt.get_unverified_header(token)
        return header.get("alg", "").startswith("RS")
    except jwt.InvalidTokenError:
        return False


async def decode_authentik_token(token: str) -> dict[str, Any]:
    """Validate an Authentik JWT and return its claims.

    The JWKS fetch is blocking (urllib) — run in a thread; subsequent calls
    hit the in-process key cache.
    """
    if not settings.AUTHENTIK_ENABLED:
        raise AuthError("Authentik authentication is not enabled")
    if not settings.AUTHENTIK_ISSUER:
        raise AuthError("AUTHENTIK_ISSUER is not configured")

    try:
        signing_key = await asyncio.to_thread(_get_jwks_client().get_signing_key_from_jwt, token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.AUTHENTIK_ISSUER,
            audience=settings.AUTHENTIK_AUDIENCE or None,
            options={"verify_aud": bool(settings.AUTHENTIK_AUDIENCE)},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Authentik token expired") from e
    except jwt.PyJWKClientError as e:
        logger.error("authentik_jwks_error", error=str(e))
        raise AuthError("Could not fetch Authentik signing keys") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"Invalid Authentik token: {e}") from e

    if not claims.get("sub"):
        raise AuthError("Authentik token missing subject")
    return claims
