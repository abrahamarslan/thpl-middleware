"""Currencies ↔ Zoho: identity, endpoint, storage contract and sync defaults.

  - GET /settings/currencies returns every currency in ONE response and the
    documented example has no page_context → ``paginated=False`` (a paginated
    walk would raise a contract error on the missing page_context).
  - The list row carries every documented attribute (currency_id, code, name,
    symbol, price_precision, format, is_base_currency, exchange_rate,
    effective_date) → ``detail_required=False``, so no ``index_then_detail``
    either. This is the deliberate exception to the usual index-then-detail
    flow: GET /settings/currencies/{id} returns the same fields the list
    already gave us, so a detail call per currency would buy nothing and cost
    one API call each against a shared daily quota. Modules whose list IS thin
    (organizations, taxes, invoices) set ``index_then_detail=True``; flipping
    currencies is a one-line change if Zoho ever thins the list.
  - No last_modified_time → FULL strategy; the apply gate's hash makes an
    unchanged list a zero-write run, so a daily pull costs exactly 1 call.
  - BIDIRECTIONAL: currencies created here are pushed to Zoho as well. The
    translator already builds the create/update bodies; the outbound *transport*
    (the command outbox) is not built yet, so nothing is dispatched today —
    ``to_zoho_payload`` in the service is the seam it will call.
  - ``crosswalk=True``: identity and gate state live in ``sync.sync_records``;
    ``currency.currencies`` holds business columns only.
"""

from app.modules.currencies.model import CURRENCY_SCHEMA, Currency
from app.modules.currencies.zoho.fields import CURRENCY_FIELDS
from app.modules.currencies.zoho.hooks import project_exchange_rates, stamp_scope
from app.modules.currencies.zoho.translator import (
    CURRENCY_TRANSLATOR,
    ZOHO_OWNED_CURRENCY_FIELDS,
)
from app.modules.sync.contract import SyncContract
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
    field_map=CURRENCY_FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table=f"{CURRENCY_SCHEMA}.currencies",
        # The business key two sources agree on. This is how SAP's USD finds the
        # row Zoho mastered instead of creating a second one.
        match_on=("currency_code",),
        crosswalk=True,
        history_raw=True,             # a tiny module: keep every document
        capture_custom_fields=True,
        # Zoho's currency_id, echoed onto the row. Both columns already exist
        # and the model documents them as "L1 source echoes"; the engine now
        # keeps them true. Identity still lives in the crosswalk — nothing
        # matches on these.
        identity_echo=("zoho_id", "currency_id"),
        owned_fields=ZOHO_OWNED_CURRENCY_FIELDS,
    ),
)

SPEC = ZohoModuleDefinition(
    config=CURRENCIES_CONFIG,
    model=Currency,
    translator=CURRENCY_TRANSLATOR,
    pre_upsert=stamp_scope,
    post_upsert=project_exchange_rates,
    tags=["settings", "o1-master"],
)

__all__ = ["CURRENCIES_CONFIG", "SPEC"]
