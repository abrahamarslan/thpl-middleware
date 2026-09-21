"""Who may operate the Zoho integration.

⚠ Interim authorisation. The platform has no RBAC yet (``users.role_id``
references a roles table that does not exist), so operators are an explicit
allow-list of emails in ``ZOHO_OPERATOR_EMAILS``:

  * listed email            → allowed
  * list empty + DEBUG=true  → any authenticated user (local development)
  * otherwise               → 403

Replace with a role/permission check (Authentik group → local role) when RBAC
lands; the dependency name stays the same so routes do not change.
"""

from typing import Annotated

from fastapi import Depends

from app.common.exception.errors import ForbiddenError
from app.core.conf import settings
from app.modules.users.deps import CurrentUser
from app.modules.users.model import User


def _operator_emails() -> set[str]:
    return {e.strip().lower() for e in settings.ZOHO_OPERATOR_EMAILS.split(",") if e.strip()}


async def require_zoho_operator(user: CurrentUser) -> User:
    allowed = _operator_emails()
    email = (getattr(user, "email", None) or "").lower()
    if (allowed and email in allowed) or (not allowed and settings.DEBUG):
        return user
    raise ForbiddenError("Zoho integration operations require an operator account")


ZohoOperator = Annotated[User, Depends(require_zoho_operator)]
