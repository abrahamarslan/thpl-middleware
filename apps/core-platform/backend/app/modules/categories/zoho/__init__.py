"""Categories Zoho adapter — registers the module spec on import.

Listed in ``app.modules.zoho.sync.registry._ADAPTER_PACKAGES``; the platform
imports it by string, never the other way round.
"""

from app.modules.categories.zoho.spec import CATEGORIES_CONFIG, SPEC
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["CATEGORIES_CONFIG", "SPEC"]
