"""First-party token issuance, shared by password and OTP login."""

from app.common.security.jwt import create_access_token, create_refresh_token
from app.core.conf import settings
from app.modules.users.model import User
from app.modules.users.schema import TokenPair


def issue_token_pair(user: User) -> TokenPair:
    claims = {"email": user.email, "role_id": user.role_id, "user_type": user.user_type}
    return TokenPair(
        access_token=create_access_token(str(user.id), claims=claims),
        refresh_token=create_refresh_token(str(user.id)),
        expires_in=settings.JWT_EXPIRATION_HOURS * 3600,
    )
