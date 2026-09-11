"""Auth transactional emails — typed contexts over the reusable email layer.

All auth emails (welcome, login OTP, password reset code/link, password changed)
are declared once here: the template files live in this module's ``templates/``
directory, and every send goes through ``send_template_email`` so rendering,
delivery, retries and logging are owned by the emails module.

The context is a **typed Pydantic model** — an enterprise pattern that turns a
missing/renamed template variable into a validation error at the call site
rather than a silently blank email. ``client`` (IP/device/GeoIP location) is the
audit block every security email shows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from app.common.client_info import ClientInfo, format_utc
from app.core.conf import settings
from app.modules.emails.model import Email
from app.modules.emails.service import send_template_email
from app.modules.emails.templates import EmailTemplate, register_template
from app.modules.users.model import User

_TEMPLATE_DIR = "app/modules/users/templates"


# ── Template registry (auth owns its templates) ──────────────────────────────

register_template(EmailTemplate(
    name="welcome",
    subject="Welcome to {{ company_name }}",
    html="welcome",
    text="welcome",
    directory=_TEMPLATE_DIR,
    required_context=("email",),
))
register_template(EmailTemplate(
    name="login_otp",
    subject="Your {{ company_name }} sign-in code",
    html="login_otp",
    text="login_otp",
    directory=_TEMPLATE_DIR,
    required_context=("code", "expires_minutes"),
))
register_template(EmailTemplate(
    name="password_reset_code",
    subject="{{ company_name }} password reset code",
    html="password_reset_code",
    text="password_reset_code",
    directory=_TEMPLATE_DIR,
    required_context=("code", "expires_minutes", "email"),
))
register_template(EmailTemplate(
    name="password_reset_link",
    subject="Reset your {{ company_name }} password",
    html="password_reset_link",
    text="password_reset_link",
    directory=_TEMPLATE_DIR,
    required_context=("reset_url", "expires_minutes", "email"),
))
register_template(EmailTemplate(
    name="password_changed",
    subject="Your {{ company_name }} password was changed",
    html="password_changed",
    text="password_changed",
    directory=_TEMPLATE_DIR,
    required_context=("email",),
))


# ── Typed contexts (the template contract) ───────────────────────────────────

class BaseAuthEmailContext(BaseModel):
    name: str | None = None
    email: str
    device: str = "Unknown device"
    location: str = "Unknown location"
    ip: str = "Unknown"
    requested_at: str


class WelcomeEmailContext(BaseAuthEmailContext):
    account_id: str | None = None
    workspace: str | None = None
    dashboard_url: str


class LoginOtpEmailContext(BaseAuthEmailContext):
    code: str
    code_formatted: str
    expires_minutes: int


class PasswordResetCodeEmailContext(BaseAuthEmailContext):
    code: str
    expires_minutes: int
    expires_at: str | None = None
    attempts_allowed: int


class PasswordResetLinkEmailContext(BaseAuthEmailContext):
    reset_url: str
    expires_minutes: int


class PasswordChangedEmailContext(BaseAuthEmailContext):
    pass


def _audit_fields(client: ClientInfo | None, at: datetime | None = None) -> dict:
    if client is not None:
        return client.email_context(at=at)
    return {
        "device": "Unknown device",
        "location": "Unknown location",
        "ip": "Unknown",
        "requested_at": format_utc(at),
    }


def account_id_for(user: User) -> str:
    return f"TH-{user.id:06d}"


async def _send(
    db,
    template: str,
    user: User,
    context: BaseAuthEmailContext,
    client: ClientInfo | None,
    *,
    purpose: str,
) -> Email:
    return await send_template_email(
        db,
        template,
        to=[user.email],
        context=context.model_dump(),
        emailable_type="User",
        emailable_id=str(user.id),
        metadata={"purpose": purpose, "template": template},
        source_ip=client.ip if client else None,
        user_agent=client.user_agent if client else None,
    )


# ── Senders ──────────────────────────────────────────────────────────────────

async def send_welcome_email(
    db, user: User, *, client: ClientInfo | None = None, workspace: str | None = None
) -> Email:
    context = WelcomeEmailContext(
        name=user.name,
        email=user.email,
        account_id=account_id_for(user),
        workspace=workspace,
        dashboard_url=f"{settings.FRONTEND_URL.rstrip('/')}/dashboard",
        **_audit_fields(client),
    )
    return await _send(db, "welcome", user, context, client, purpose="welcome")


async def send_login_otp_email(
    db, user: User, *, code: str, expires_minutes: int, client: ClientInfo | None = None
) -> Email:
    formatted = f"{code[:3]}-{code[3:]}" if len(code) > 3 else code
    context = LoginOtpEmailContext(
        name=user.name,
        email=user.email,
        code=code,
        code_formatted=formatted,
        expires_minutes=expires_minutes,
        **_audit_fields(client),
    )
    return await _send(db, "login_otp", user, context, client, purpose="login_otp")


async def send_password_reset_code_email(
    db,
    user: User,
    *,
    code: str,
    expires_minutes: int,
    expires_at: datetime | None = None,
    attempts_allowed: int,
    client: ClientInfo | None = None,
) -> Email:
    formatted_expiry = (
        f"{expires_at.astimezone(UTC):%H:%M} UTC" if expires_at else None
    )
    context = PasswordResetCodeEmailContext(
        name=user.name,
        email=user.email,
        code=code,
        expires_minutes=expires_minutes,
        expires_at=formatted_expiry,
        attempts_allowed=attempts_allowed,
        **_audit_fields(client),
    )
    return await _send(db, "password_reset_code", user, context, client, purpose="password_reset")


async def send_password_reset_link_email(
    db,
    user: User,
    *,
    reset_url: str,
    expires_minutes: int,
    client: ClientInfo | None = None,
) -> Email:
    context = PasswordResetLinkEmailContext(
        name=user.name,
        email=user.email,
        reset_url=reset_url,
        expires_minutes=expires_minutes,
        **_audit_fields(client),
    )
    return await _send(db, "password_reset_link", user, context, client, purpose="password_reset")


async def send_password_changed_email(
    db, user: User, *, client: ClientInfo | None = None
) -> Email:
    context = PasswordChangedEmailContext(
        name=user.name,
        email=user.email,
        **_audit_fields(client),
    )
    return await _send(db, "password_changed", user, context, client, purpose="password_changed")
