"""Currencies Zoho adapter — self-registers on import (package-by-feature).

``app/modules/zoho/sync/registry.py`` imports this package by string; the
platform never imports a feature module directly.
"""

from app.modules.currencies.zoho.spec import CURRENCIES_CONFIG, SPEC
from app.modules.currencies.zoho.translator import (
    CURRENCY_TRANSLATOR,
    ZOHO_OWNED_CURRENCY_FIELDS,
)
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["CURRENCIES_CONFIG", "CURRENCY_TRANSLATOR", "SPEC", "ZOHO_OWNED_CURRENCY_FIELDS"]
