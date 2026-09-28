"""Brands ↔ Zoho Books: a real, undocumented ``/brands`` resource, organization-scoped.

Every choice below was checked against the live API (2026-09-28) — there is no
vendored doc to work from:

  - ``GET /brands`` returns ``{code, message, brands: [{brand_id, name}]}`` — no
    ``page_context`` → ``paginated=False`` (the currencies precedent).
  - ``per_page``/``page`` query params are silently ignored (still returns every
    row); confirms the endpoint is a single unpaginated response, not merely a
    small org.
  - ``GET /brands/{id}`` returns the identical two fields the list already gave
    → ``detail_required=False``, no ``index_then_detail`` (again the currencies
    precedent — a detail call would buy nothing and cost a call against the
    shared daily quota).
  - ``last_modified_time`` is accepted as a query param but has **no filtering
    effect** — every row still comes back. Declaring ``INCREMENTAL`` against a
    filter that silently does nothing would be worse than not declaring it:
    the engine's cursor bookkeeping would run for nothing, and a future reader
    would believe narrowing happens when it does not. → ``FULL``,
    ``modified_since_param=None``.
  - Items reference a brand by its NAME string, not ``brand_id`` — Zoho does not
    expose a cross-reference here, so nothing downstream resolves through it yet.
  - ``direction=INBOUND``: only GET was verified. No push is built and none is
    claimed; ``to_zoho_payload`` is deliberately NOT provided (unlike
    currencies/categories) because writing one would imply the create/update
    body shape is known, and it is not.
  - ``crosswalk=True``, ``match_on=()``: a Zoho brand is never auto-merged into
    a same-named local one — the ``taxes`` module's rule ("two authorities can
    share a name; never invent a match"). A genuine collision fails loudly at
    ``uq_brands_scope_name`` instead of silently duplicating or merging.
  - This reverses ``Brand``'s original "not a Zoho mirror" design — a deliberate
    decision made on the user's explicit instruction once this endpoint was
    confirmed live. See ``docs/implementation-plan/brands-zoho-sync.md``.
"""

from app.modules.brands.model import Brand
from app.modules.brands.zoho.fields import FIELDS
from app.modules.brands.zoho.hooks import stamp_scope
from app.modules.sync.contract import SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

BRANDS_TRANSLATOR = FieldTranslator("brands", FIELDS)

#: Columns Zoho owns on a linked row. Derived, never hand-listed. Every other
#: brand column (slug, code, kind, parent_id, country_code, description,
#: website_url, logo_storage_key) has no Zoho counterpart and stays ours.
ZOHO_OWNED_BRAND_FIELDS: frozenset[str] = frozenset(BRANDS_TRANSLATOR.readable)

BRANDS_CONFIG = resolve_module_config(
    module="brands",
    endpoint="/brands",
    zoho_id_attr="brand_id",
    api="books",
    paginated=False,
    strategy=SyncStrategyName.FULL,
    direction=SyncDirection.INBOUND,
    detail_required=False,
    modified_since_param=None,
    sort_column=None,
    sync_interval_minutes=1440,       # daily; a 7-row vocabulary changes rarely
    weekly_full_enabled=False,        # the scheduled lane already IS a full scan
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="core.brands",
        match_on=(),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=True,
        identity_echo=("zoho_id",),
        owned_fields=ZOHO_OWNED_BRAND_FIELDS,
    ),
)

SPEC = ZohoModuleDefinition(
    config=BRANDS_CONFIG,
    model=Brand,
    translator=BRANDS_TRANSLATOR,
    pre_upsert=stamp_scope,
    tags=["core", "catalog"],
)

__all__ = ["BRANDS_CONFIG", "BRANDS_TRANSLATOR", "SPEC", "ZOHO_OWNED_BRAND_FIELDS"]
