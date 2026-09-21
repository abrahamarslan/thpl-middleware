"""Taxes Zoho adapter — registers the module spec on import."""

from app.modules.taxes.zoho.spec import SPEC, TAXES_CONFIG
from app.modules.zoho.sync.registry import sync_registry

sync_registry.register(SPEC)

__all__ = ["SPEC", "TAXES_CONFIG"]
