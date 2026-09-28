"""Categories ↔ Zoho Books: the ``/categories`` tree, organization-scoped.

Every choice below was checked against the live API (2026-09-25), not only the
vendored doc (docs/zoho-docs-md/categories.md):

  - ``GET /categories`` returns a ``page_context`` → ``paginated=True``.
  - **It also returns a synthetic ROOT row** — ``category_id: "-1"``,
    ``name: "ROOT"``, blank ``created_time`` / ``last_modified_time`` — that is
    the parent every top-level category names. It is not a category anyone
    created, so ``include_root_category=false`` (documented) keeps it out: with
    it, a sync imported a fake top-level "ROOT" node beside the real roots and,
    because its modified time is blank, an incremental run re-listed it every
    time.
  - The ``last_modified_time`` filter works and takes the engine's own
    ``…+0000`` cursor format; the doc's ``…Z`` spelling is rejected with a 400
    → ``INCREMENTAL``. ``sort_column`` is left ``None`` on purpose: Zoho's
    default sort is ``sibling_order`` (hierarchical), and the engine only
    advances its watermark page by page for a TIME-ordered scan.
  - **Deletes never appear in an incremental list.** The weekly-full lane
    (``weekly_full_enabled``, on by default) re-lists everything and
    ``soft_delete_missing`` lets that scan tombstone what Zoho no longer has —
    still behind the ``ZOHO_SYNC_ALLOW_SOFT_DELETE_MISSING`` switch and the
    mass-delete guard.
  - ``detail_required`` + ``index_then_detail``: the list row carries the tree
    fields; only the detail document has the SEO block, ``custom_fields`` and
    ``category_tax_preferences``. The apply gate makes the steady state free —
    a row that already holds its detail document of the listed version spends
    no call.
  - ``direction=INBOUND``: Zoho masters the tree (names, order, parent), so a
    local edit to a linked row is refused (``service._guard_zoho_owned``).
    Declaring BIDIRECTIONAL while refusing those edits contradicted itself, and
    nothing would have dispatched the push anyway — the command outbox is not
    built platform-wide yet (see ``currencies/zoho/spec.py``).
    ``service.to_zoho_payload`` stays as the seam the outbox will call.
  - ``crosswalk=True``: identity and gate state live in ``sync.sync_records``;
    ``core.categories`` holds business columns plus the ``zoho_id`` echo.
  - ``match_on=("zoho_id",)``: the echo is not the identity (the crosswalk is),
    but if the crosswalk were ever emptied it lets the next sync re-adopt the
    rows that still carry the id instead of inserting duplicates.
"""

from app.modules.categories.model import Category
from app.modules.categories.zoho.fields import FIELDS
from app.modules.categories.zoho.hooks import after_category_upsert, normalise_category
from app.modules.sync.contract import SyncContract
from app.modules.sync.translation import FieldTranslator
from app.modules.zoho.sync.config import SyncDirection, SyncStrategyName, resolve_module_config
from app.modules.zoho.sync.registry import ZohoModuleDefinition

CATEGORIES_TRANSLATOR = FieldTranslator("categories", FIELDS)

#: Columns Zoho owns on a linked row. Derived, never hand-listed: every field
#: the translator reads, plus ``parent_id`` — the hierarchy is Zoho's too (the
#: hook re-links it from ``parent_category_id`` on every re-apply, so a local
#: move would be silently undone). A local edit to one of these is refused by
#: the service (change it in Zoho).
ZOHO_OWNED_CATEGORY_FIELDS: frozenset[str] = frozenset(CATEGORIES_TRANSLATOR.readable) | {"parent_id"}

CATEGORIES_CONFIG = resolve_module_config(
    module="categories",
    endpoint="/categories",
    zoho_id_attr="category_id",
    api="books",
    paginated=True,
    strategy=SyncStrategyName.INCREMENTAL,
    direction=SyncDirection.INBOUND,
    detail_required=True,
    detail_dispatch="inline",
    index_then_detail=True,
    modified_since_param="last_modified_time",
    sort_column=None,
    list_params={"include_root_category": "false"},
    soft_delete_missing=True,
    sync_interval_minutes=360,
    wait_between_calls=0.2,
    field_map=FIELDS,
    contract=SyncContract(
        source_system="zoho",
        entity_table="core.categories",
        match_on=("zoho_id",),
        crosswalk=True,
        history_raw=True,
        capture_custom_fields=True,
        identity_echo=("zoho_id",),
        owned_fields=ZOHO_OWNED_CATEGORY_FIELDS,
    ),
)

SPEC = ZohoModuleDefinition(
    config=CATEGORIES_CONFIG,
    model=Category,
    translator=CATEGORIES_TRANSLATOR,
    pre_upsert=normalise_category,
    post_upsert=after_category_upsert,
    tags=["core", "catalog"],
)

__all__ = [
    "CATEGORIES_CONFIG",
    "CATEGORIES_TRANSLATOR",
    "SPEC",
    "ZOHO_OWNED_CATEGORY_FIELDS",
]
