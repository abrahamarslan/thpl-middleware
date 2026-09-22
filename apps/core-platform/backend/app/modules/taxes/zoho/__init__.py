"""Taxes Zoho adapter — self-registers its three modules on import (package-by-feature)."""

from app.modules.taxes.zoho.spec import (
    SPEC,
    TAX_EXEMPTIONS_SPEC,
    TAX_GROUPS_SPEC,
    TAXES_CONFIG,
    ZOHO_OWNED_TAX_FIELDS,
)
from app.modules.taxes.zoho.translator import TAX_TRANSLATOR
from app.modules.zoho.sync.registry import sync_registry

for _spec in (SPEC, TAX_GROUPS_SPEC, TAX_EXEMPTIONS_SPEC):
    sync_registry.register(_spec)

__all__ = ["SPEC", "TAXES_CONFIG", "TAX_EXEMPTIONS_SPEC", "TAX_GROUPS_SPEC", "TAX_TRANSLATOR",
           "ZOHO_OWNED_TAX_FIELDS"]
