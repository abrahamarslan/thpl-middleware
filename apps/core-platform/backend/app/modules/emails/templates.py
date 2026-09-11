"""Reusable transactional-email templates: registry + one render path.

A template is registered once (name, subject, html/text base names, owning
directory, required context keys) and rendered through one function. Callers
ask for a template name and a context dict — never for an HTML string — so a
new email is a new registry entry, not a new branch in the sender (registries-
over-conditionals doctrine).

Templates may live in **any module's** directory (``EmailTemplate.directory``,
defaulting to ``EMAIL_TEMPLATE_DIR``); the Jinja environment uses a
``ChoiceLoader`` across every registered directory, so auth owns its auth
templates, billing would own billing templates, and so on. ``required_context``
turns a missing template variable into a loud ``TemplateContextError`` at send
time rather than a silently blank email.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from app.common.exception.errors import AppError
from app.core.conf import settings


class TemplateNotFoundError(AppError):
    status_code = 500
    code = "email_template_not_found"


class TemplateContextError(AppError):
    """A template was rendered without a required context key."""

    status_code = 500
    code = "email_template_context"


@dataclass(frozen=True, slots=True)
class EmailTemplate:
    """Registry entry. ``subject`` is itself a Jinja2 string."""

    name: str
    subject: str
    html: str | None = None            # file base name (no locale/extension)
    text: str | None = None
    directory: str | None = None       # defaults to settings.EMAIL_TEMPLATE_DIR
    default_locale: str | None = None
    required_context: tuple[str, ...] = ()


_TEMPLATES: dict[str, EmailTemplate] = {}
_environment: Environment | None = None
_loaded_dirs: tuple[str, ...] = ()


def register_template(template: EmailTemplate) -> None:
    _TEMPLATES[template.name] = template
    # A new directory invalidates the cached environment's loader.
    global _environment
    _environment = None


def get_template(name: str) -> EmailTemplate:
    try:
        return _TEMPLATES[name]
    except KeyError:
        raise TemplateNotFoundError(f"Unknown email template: {name}") from None


def registered_names() -> list[str]:
    return sorted(_TEMPLATES)


def _template_dirs() -> tuple[str, ...]:
    dirs = {settings.EMAIL_TEMPLATE_DIR}
    dirs.update(t.directory for t in _TEMPLATES.values() if t.directory)
    return tuple(sorted(dirs))


def get_environment() -> Environment:
    """Lazy Jinja2 environment spanning every registered template directory."""
    global _environment, _loaded_dirs
    current = _template_dirs()
    if _environment is None or _loaded_dirs != current:
        loader = ChoiceLoader([FileSystemLoader(str(Path(d))) for d in current])
        _environment = Environment(
            loader=loader,
            autoescape=select_autoescape(["html", "htm", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _loaded_dirs = current
    return _environment


@dataclass(slots=True)
class RenderedEmail:
    template_name: str
    subject: str
    html: str | None
    text: str | None
    locale: str
    context: dict = field(default_factory=dict)


def _render_file(env: Environment, base: str | None, locale: str, extension: str, ctx: dict) -> str | None:
    """Resolve ``<base>.<locale><ext>`` → default locale → locale-less."""
    if not base:
        return None
    available = set(env.list_templates())
    for stem in (f"{base}.{locale}", f"{base}.{settings.EMAIL_DEFAULT_LOCALE}", base):
        candidate = f"{stem}{extension}"
        if candidate in available:
            return env.get_template(candidate).render(**ctx)
    return None


def render_email(name: str, context: dict | None = None, *, locale: str | None = None) -> RenderedEmail:
    """Render a registered template to subject/html/text.

    Global brand values (``company_name``, ``support_email``, ``company_address``,
    ``site_url``, ``frontend_url``, ``year``) are injected automatically; caller
    context wins on key collisions. Missing ``required_context`` keys raise.
    """
    template = get_template(name)
    locale = locale or template.default_locale or settings.EMAIL_DEFAULT_LOCALE
    env = get_environment()

    ctx: dict = {
        "company_name": settings.EMAIL_COMPANY_NAME,
        "support_email": settings.EMAIL_SUPPORT_EMAIL,
        "company_address": settings.EMAIL_COMPANY_ADDRESS,
        "site_url": settings.EMAIL_SITE_URL.rstrip("/"),
        "frontend_url": settings.FRONTEND_URL.rstrip("/"),
        "year": datetime.now(UTC).year,
        "locale": locale,
        **(context or {}),
    }
    missing = [key for key in template.required_context if ctx.get(key) in (None, "")]
    if missing:
        raise TemplateContextError(
            f"Template '{name}' missing required context: {', '.join(missing)}"
        )

    subject = env.from_string(template.subject).render(**ctx)
    return RenderedEmail(
        template_name=template.name,
        subject=subject.strip(),
        html=_render_file(env, template.html, locale, ".html", ctx),
        text=_render_file(env, template.text, locale, ".txt", ctx),
        locale=locale,
        context=ctx,
    )
