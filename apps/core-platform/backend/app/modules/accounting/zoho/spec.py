"""Chart of accounts ↔ Zoho: identity, endpoint, storage contract and sync defaults.

  GET /chartofaccounts[/{account_id}]   → accounting.accounts      (module ``chart_of_accounts``)

  - **FULL by default** (owner decision 2026-10-08). The list documents a
    ``last_modified_time`` filter and the owner trusts it, so ``modified_since_param`` is
    declared: switching to INCREMENTAL is a control-plane override
    (``{"strategy": "incremental", "weekly_full_enabled": true}``), no deploy. Under FULL the
    apply gate makes an unchanged chart nearly free (hash per row, no write, no detail call).
  - ``sort_column=None``: Zoho sorts only by ``account_name`` / ``account_type``, neither
    time-ordered, so the engine must not advance a page watermark.
  - **List-only by default** (``detail_required=False``). The list row carries everything the
    chart and its assignments need — id, name, code, type, parent, status. A detail call per
    account costs one request each against Zoho's documented limits (docs/zoho-docs-md/
    introduction.md: 100 requests/minute per organization; 1 000–10 000 requests/DAY by plan),
    so a 300-account chart would spend 300 calls on every full scan — 15 % of a Standard plan's
    day — for ``description`` / ``custom_fields`` and, where the list omits it, ``currency_id``.
    Enabling detail is a control-plane override, no deploy:
    ``{"detail_required": true, "index_then_detail": true, "wait_between_calls": 1.0}``.
    Observed live (2026-10-08, one occurrence each — NOT documented figures): with detail on, the
    first full sync of THPL's chart got HTTP 429 with an undocumented ``code: 43`` ("blocked for
    some time … requests per minute") after ~190 detail calls in ~3.5 min although this process
    stayed at ≤ 58 calls/minute by its own log, and the block took ~15–20 min to lift. Zoho's
    documented per-ACCOUNT variant counts the connected user's web-UI and other-app traffic too,
    which may explain it; we could not verify. A 429 also fails the whole run (the engine rolls
    the run back), so detail-on first syncs of large charts may not converge — keep it off.
  - **Never ``showbalance=true``**: a balance changes without the account changing; it would
    make every scan a write (and the balance keys are volatile in the hash anyway).
  - ``direction=INBOUND``: Zoho masters the chart; a linked account's Zoho-fed fields are
    read-only through the API. ``service.to_zoho_payload`` is the seam the outbox will call.
  - ``crosswalk=True`` + ``identity_echo=("zoho_id",)``; ``match_on=("zoho_id",)`` only
    re-adopts rows if the crosswalk were ever emptied — never a business-key merge (Zoho
    repeats child names across branches; a name match would merge two ledgers).
  - ``currency_id`` → ``currencies`` via ``ReferenceRule`` (DEFER: NULL = base currency until
    the reconcile lane links it).
  - Tenant / organization: the connection's organization (``ZOHO_ORGANIZATION_ID`` → THPL),
    else ``DEFAULT_TENANT_CODE`` / ``DEFAULT_ORGANIZATION_CODE`` (delta-v3 §2.1).
"""

from app.modules.accounting.model import Account
from app.modules.accounting.zoho.fields import FIELDS, VOLATILE_KEYS
from app.modules.accounting.zoho.hooks import MODULE, after_account_upsert
from app.modules.sync.contract import OnMissing, ReferenceRule, SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

CHART_OF_ACCOUNTS_TRANSLATOR = FieldTranslator(MODULE, FIELDS)

#: Columns Zoho owns on a linked account: every field the translator reads, plus the parent
#: and the currency (both re-linked by every apply). Derived, never hand-listed.
ZOHO_OWNED_ACCOUNT_FIELDS: frozenset[str] = (
    frozenset(CHART_OF_ACCOUNTS_TRANSLATOR.readable) | {"parent_id", "currency_id"}
)

CHART_OF_ACCOUNTS_CONFIG = resolve_module_config(
    module=MODULE,
    endpoint="/chartofaccounts",
    zoho_id_attr="account_id",
    api="books",
    paginated=True,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,              # list-only: see the module docstring (documented API limits)
    detail_dispatch="inline",
    index_then_detail=False,
    modified_since_param="last_modified_time",
    sort_column=None,
    sync_interval_minutes=1440,
    weekly_full_enabled=False,          # the scheduled lane already IS full; enable with the INCREMENTAL override
    # Only paces detail calls, which are off by default. If detail is switched on, keep at least this:
    # well under the documented 100 requests/minute per organization (docs/zoho-docs-md/introduction.md).
    wait_between_calls=1.0,
    hash_volatile_keys=VOLATILE_KEYS,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="accounting.accounts",
        match_on=("zoho_id",),
        crosswalk=True,
        identity_echo=("zoho_id",),
        history_raw=True,
        capture_custom_fields=True,
        owned_fields=ZOHO_OWNED_ACCOUNT_FIELDS,
        references=(
            ReferenceRule(attr="currency_id", module="currencies", fk="currency_id", on_missing=OnMissing.DEFER),
        ),
    ),
)

SPEC = ZohoModuleDefinition(
    config=CHART_OF_ACCOUNTS_CONFIG,
    model=Account,
    translator=CHART_OF_ACCOUNTS_TRANSLATOR,
    post_upsert=after_account_upsert,
    tags=["accounting", "o1-master"],
)

__all__ = [
    "CHART_OF_ACCOUNTS_CONFIG",
    "CHART_OF_ACCOUNTS_TRANSLATOR",
    "SPEC",
    "ZOHO_OWNED_ACCOUNT_FIELDS",
]
