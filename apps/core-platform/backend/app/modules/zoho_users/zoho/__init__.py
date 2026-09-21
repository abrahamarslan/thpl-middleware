"""Zoho users adapter — registers the module spec on import."""

from app.modules.zoho.sync.registry import sync_registry
from app.modules.zoho_users.zoho.spec import SPEC, USERS_CONFIG

sync_registry.register(SPEC)

__all__ = ["SPEC", "USERS_CONFIG"]
