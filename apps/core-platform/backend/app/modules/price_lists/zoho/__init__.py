"""Price lists Zoho adapter (Zoho endpoint ``/pricebooks``) — registers the module spec on import.

Listed in ``app.modules.zoho.sync.registry._ADAPTER_PACKAGES``; the platform imports it by
string, never the other way round.
"""

from app.modules.price_lists.zoho.spec import PRICE_LISTS_CONFIG, SPEC
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["PRICE_LISTS_CONFIG", "SPEC"]
