"""Price lists ↔ Zoho: identity, endpoint, storage contract and sync defaults.

  GET /pricebooks            → pricing.price_lists                          (module ``price_lists``)
  GET /pricebooks/{id}       → + pricing.price_list_items / price_list_item_brackets (hook)

Zoho's API names the resource *pricebook*; the module, tables and routes say *price list*. The module
key was ``pricebooks`` until migration ``20261008_1600_7c3e91a05d24``, which renamed every stored
reference (crosswalk, history, runs, events, cursors, stats, overrides).

Zoho's price-list docs (https://www.zoho.com/books/api/v3/pricelists/) document create, list,
update, delete and mark active/inactive — but NO "get a price list". ``GET /pricebooks/{id}``
works live (probed 2026-10-08, every type/scheme/side) and is the only source of the items and
brackets, so the adapter depends on it. If Zoho ever withdraws it, the detail phase fails per
record and the lists keep their list-row columns (index_then_detail): degraded, not broken.

  - **FULL** (the platform default). The list documents NO modified-since filter, so
    ``modified_since_param=None``: an INCREMENTAL override would silently degrade to FULL.
    ``sort_column=None`` (no time-ordered sort is documented).
  - **detail_required + index_then_detail.** The list row has every header column except
    ``is_default``; the items exist only in the detail. The row is written from the list first,
    then completed from the detail (one call per list, paced by ``wait_between_calls``).
  - **detail_max_age_minutes=1440.** The gate skips a detail whose listed
    ``last_modified_time`` has not moved. Zoho does not document whether editing an item rate
    bumps the LIST's timestamp, and the detail document carries no timestamp of its own, so the
    timestamp alone cannot be trusted for the children: each list's detail is re-confirmed at
    least once a day (one call per list; an unchanged document writes nothing and only stamps
    ``raw_synced_at``). Tunable live through the control plane, no deploy.
  - **soft_delete_missing** — a full scan returns active AND inactive lists (verified live), so a
    list absent from a complete scan was deleted in Zoho. The engine's guards apply
    (``ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING``, the mass-delete ceiling). A tombstoned list's
    children are left as they were — unreachable, because every read goes through a live list.
  - ``direction=INBOUND``: Zoho masters price lists; the API is read-only.
  - ``crosswalk=True`` + ``identity_echo=("zoho_id",)``; ``match_on=("zoho_id",)`` only re-adopts
    rows if the crosswalk were ever emptied — never a name merge (two lists may share a name
    across sales/purchases).
  - ``currency_id`` → ``currencies`` via ``ReferenceRule`` (DEFER); ``""`` = base currency, which
    the hook writes as NULL.
  - Tenant / organization: the connection's organization (``ZOHO_ORGANIZATION_ID`` → THPL), else
    ``DEFAULT_TENANT_CODE`` / ``DEFAULT_ORGANIZATION_CODE``.
"""

from app.modules.price_lists.model import PriceList
from app.modules.price_lists.zoho.fields import FIELDS, VOLATILE_KEYS
from app.modules.price_lists.zoho.hooks import MODULE, after_price_list_upsert
from app.modules.sync.contract import OnMissing, ReferenceRule, SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

PRICE_LISTS_TRANSLATOR = FieldTranslator(MODULE, FIELDS)

#: Columns Zoho owns on a linked price list: every field the translator reads, plus the currency.
ZOHO_OWNED_PRICE_LIST_FIELDS: frozenset[str] = frozenset(PRICE_LISTS_TRANSLATOR.readable) | {"currency_id"}

PRICE_LISTS_CONFIG = resolve_module_config(
    module=MODULE,
    endpoint="/pricebooks",             # Zoho's name for the resource
    zoho_id_attr="pricebook_id",
    api="books",
    paginated=True,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    detail_max_age_minutes=1440,
    modified_since_param=None,          # not documented for GET /pricebooks
    sort_column=None,
    soft_delete_missing=True,
    sync_interval_minutes=360,
    weekly_full_enabled=False,          # every scheduled run already IS full
    # Paces detail calls: well under the documented 100 requests/minute per organization
    # (docs/zoho-docs-md/introduction.md).
    wait_between_calls=1.0,
    hash_volatile_keys=VOLATILE_KEYS,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="pricing.price_lists",
        match_on=("zoho_id",),
        crosswalk=True,
        identity_echo=("zoho_id",),
        history_raw=True,
        capture_custom_fields=False,
        owned_fields=ZOHO_OWNED_PRICE_LIST_FIELDS,
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id", on_missing=OnMissing.DEFER),
        ),
    ),
)

SPEC = ZohoModuleDefinition(
    config=PRICE_LISTS_CONFIG,
    model=PriceList,
    translator=PRICE_LISTS_TRANSLATOR,
    post_upsert=after_price_list_upsert,
    tags=["pricing", "o1-master"],
)

__all__ = ["PRICE_LISTS_CONFIG", "PRICE_LISTS_TRANSLATOR", "SPEC", "ZOHO_OWNED_PRICE_LIST_FIELDS"]
