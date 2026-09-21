"""Taxes ↔ Zoho: identity, endpoint and sync defaults.

  - GET /settings/taxes is paginated (page_context in the documented response).
  - The list row carries every attribute we mirror → no detail call.
  - No last_modified_time → FULL strategy; unchanged pages write nothing
    (apply-gate hash), so a daily pull costs one call per 200 taxes.
  - INBOUND only (O1 master managed in Zoho).
"""

from app.modules.taxes.model import ZohoTax
from app.modules.taxes.zoho.fields import FIELDS
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

TAXES_CONFIG = resolve_module_config(
    module="taxes",
    endpoint="/settings/taxes",
    zoho_id_attr="tax_id",
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,
    field_map=FIELDS,
)

SPEC = ZohoModuleDefinition(config=TAXES_CONFIG, model=ZohoTax, tags=["settings", "o1-master"])
