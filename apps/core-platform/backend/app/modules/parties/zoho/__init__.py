"""Parties Zoho adapter (Zoho endpoint ``/contacts``) — registers the module spec on import.

Listed in ``app.modules.zoho.sync.registry._ADAPTER_PACKAGES``; the platform imports it by string.
"""

from app.modules.parties.zoho.spec import PARTIES_CONFIG, SPEC
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["PARTIES_CONFIG", "SPEC"]
