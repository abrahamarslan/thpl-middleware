"""Module-level message resolver for unified API response envelopes.

Design:
- Each module provides its own localized language catalogs, e.g.:
    app.modules.users.lang.en
    app.modules.zoho.auth.lang.en
- Language resolution checks:
    1. Explicit `lang` argument if passed
    2. Contextvar set from `Accept-Language` header
    3. Fallback to default ("en")
- Zero disk I/O per request: Catalogs are cached in memory after first import.
"""

from __future__ import annotations

import contextvars
import importlib
from typing import Any

import structlog

logger = structlog.get_logger("app.common.response.messages")

# Current request language context (e.g. set by middleware or header dependency)
_CURRENT_LANGUAGE: contextvars.ContextVar[str] = contextvars.ContextVar("current_language", default="en")

# In-memory catalog cache: (module_name, lang) -> dict[str, str]
_CATALOG_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def set_current_language(lang: str) -> None:
    """Set the active language for the current request context."""
    clean_lang = (lang or "en").split(",")[0].split(";")[0].split("-")[0].strip().lower()
    _CURRENT_LANGUAGE.set(clean_lang or "en")


def get_current_language() -> str:
    """Get the active language from the current request context."""
    return _CURRENT_LANGUAGE.get()


def load_module_catalog(module: str, lang: str = "en") -> dict[str, str]:
    """Dynamically load and cache a module's language dictionary."""
    cache_key = (module, lang)
    if cache_key in _CATALOG_CACHE:
        return _CATALOG_CACHE[cache_key]

    clean_module = module.replace("/", ".").strip(".")
    module_path = f"app.modules.{clean_module}.lang.{lang}"
    try:
        mod = importlib.import_module(module_path)
        catalog = getattr(mod, "MESSAGES", {})
        _CATALOG_CACHE[cache_key] = catalog
        return catalog
    except ModuleNotFoundError:
        # If requested language is not English, try falling back to English
        if lang != "en":
            return load_module_catalog(module, "en")
        logger.debug("language_catalog_not_found", module=module, lang=lang, path=module_path)
        _CATALOG_CACHE[cache_key] = {}
        return {}


def get_message(
    module: str,
    key: str,
    lang: str | None = None,
    default: str | None = None,
    **kwargs: Any,
) -> str:
    """Retrieve and format a localized message for a module.

    Example:
        msg = get_message("users", "register_success")
        msg = get_message("users", "welcome_user", name="Alice")
    """
    effective_lang = lang or get_current_language()
    catalog = load_module_catalog(module, effective_lang)
    template = catalog.get(key)

    if template is None:
        if effective_lang != "en":
            # Fallback to English catalog
            en_catalog = load_module_catalog(module, "en")
            template = en_catalog.get(key)

    if template is None:
        template = default or key

    if kwargs and template:
        try:
            return template.format(**kwargs)
        except Exception as err:
            logger.warning("message_format_failed", template=template, error=str(err))
            return template

    return template
