"""Currencies Zoho adapter — registers the module spec on import."""

from app.modules.zoho_currencies.zoho.spec import CURRENCIES_CONFIG, SPEC
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["CURRENCIES_CONFIG", "SPEC"]
