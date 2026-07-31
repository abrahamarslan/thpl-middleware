"""First-party JWT helpers (HS256 access + refresh tokens).

Two token sources exist in production:
  1. Authentik (OIDC, RS256) — humans signing in through the React frontend.
     Validated against Authentik's JWKS (app/common/security/authentik.py).
  2. First-party HS256 tokens — issued by /api/auth/login for mobile apps
     and service clients, minted here.

The user-resolving dependency that accepts BOTH lives in
app/modules/users/deps.py (it needs DB access for JIT provisioning).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.common.exception.errors import AuthError
from app.core.conf import settings

bearer_scheme = HTTPBearer(auto_error=False)


def _create_token(subject: str, *, token_type: str, lifetime: timedelta, claims: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "iss": settings.APP_NAME,
        **(claims or {}),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, *, claims: dict[str, Any] | None = None) -> str:
    return _create_token(subject, token_type="access",
                         lifetime=timedelta(hours=settings.JWT_EXPIRATION_HOURS), claims=claims)


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, token_type="refresh",
                         lifetime=timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS))


def decode_token(token: str, *, expected_type: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.APP_NAME,
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError("Invalid token") from e

    if payload.get("type", "access") != expected_type:
        raise AuthError(f"Expected a {expected_type} token")
    return payload


async def get_current_subject(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, Any]:
    """Claims-only dependency (first-party tokens). For endpoints that need
    the full DB user (or Authentik support), use users.deps.CurrentUser."""
    if credentials is None:
        raise AuthError("Missing bearer token")
    return decode_token(credentials.credentials)


CurrentSubject = Annotated[dict[str, Any], Depends(get_current_subject)]
