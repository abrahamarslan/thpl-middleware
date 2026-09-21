"""Locations Zoho adapter — registers the module spec on import."""

from app.modules.locations.zoho.spec import LOCATIONS_CONFIG, SPEC
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["LOCATIONS_CONFIG", "SPEC"]
