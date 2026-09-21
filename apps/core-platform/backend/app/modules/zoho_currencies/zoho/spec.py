"""Currencies ↔ Zoho: identity, endpoint and sync defaults.

  - GET /settings/currencies returns every currency in ONE response and the
    documented example has no page_context → ``paginated=False`` (a paginated
    walk would raise a contract error on the missing page_context).
    **[verify]** Phase 0: confirm against the live org.
  - The list row carries every attribute we mirror → no detail call.
  - No last_modified_time → FULL strategy; the apply gate's hash makes an
    unchanged list a zero-write run, so a daily pull costs exactly 1 call.
  - INBOUND only: currencies are managed in Zoho (O1 master).
"""

from app.modules.zoho_currencies.model import ZohoCurrency
from app.modules.zoho_currencies.zoho.fields import FIELDS
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

CURRENCIES_CONFIG = resolve_module_config(
    module="currencies",
    endpoint="/settings/currencies",
    zoho_id_attr="currency_id",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,       # daily; exchange rates are edited rarely
    weekly_full_enabled=False,        # the scheduled lane already IS a full scan
    field_map=FIELDS,
)

SPEC = ZohoModuleDefinition(config=CURRENCIES_CONFIG, model=ZohoCurrency, tags=["settings", "o1-master"])
