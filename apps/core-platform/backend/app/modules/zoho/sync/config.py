"""Hierarchical sync configuration (the Python replacement for zoho-modules.php).

Three layers, merged most-specific-wins:

  1. Code defaults        — the field defaults on ``GlobalSyncDefaults``.
  2. Environment          — ``ZOHO_SYNC_*`` settings (app/core/conf.py) can
                            override the global defaults fleet-wide.
  3. Module declaration   — each entity module declares a ``ModuleSyncConfig``
                            with only the knobs it wants to override, plus its
                            identity (endpoint, id attribute) and field map.

Resolution happens once at registration time via ``resolve_module_config``,
so the engine always works with a fully-materialised, validated config.

Example (organizations module):

    ORGANIZATIONS_CONFIG = resolve_module_config(
        module="organizations",
        endpoint="/organizations",
        zoho_id_attr="organization_id",
        strategy=SyncStrategyName.FULL,      # Zoho orgs have no modified filter
        detail_required=True,                # list payload is a thin index
        direction=SyncDirection.BIDIRECTIONAL,
        field_map=[FieldMapping(zoho="name", local="name"), ...],
    )
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.conf import settings
from app.modules.sync.contract import SyncContract
from app.modules.sync.translation import FieldSpec


class SyncDirection(str, Enum):
    """Which way records flow for a module."""

    INBOUND = "inbound"                # Zoho -> local only
    OUTBOUND = "outbound"              # local -> Zoho only
    BIDIRECTIONAL = "bidirectional"    # both (inbound sync + outbox pushes)
    DISABLED = "disabled"              # registered but never synced


class SyncStrategyName(str, Enum):
    """Inbound strategies implemented by the engine."""

    FULL = "full"                # paginate everything (+ optional N+1 details)
    INCREMENTAL = "incremental"  # only records modified since the last cursor
    INDEX = "index"              # list endpoint only — never N+1 detail calls


#: One external-attribute <-> local-column rule. The type now lives in the
#: source-neutral translation layer (app/modules/sync/translation.py), which
#: added the direction/codec vocabulary; this alias keeps every existing module
#: spec (``FieldMapping(zoho=..., transform=..., outbound=False)``) working
#: unchanged, because those spellings are accepted keyword aliases there.
FieldMapping = FieldSpec


class NestedEntityRule(BaseModel):
    """Routes an embedded object inside a parent payload to its own module.

    Zoho embeds related records (a Contact payload carries a ``currency``
    object and a ``tax_groups`` array). The engine extracts each nested
    payload, upserts it through the owning module's definition FIRST (so the
    child row and its local PK exist), then writes the child's identifiers
    back onto the parent row.
    """

    model_config = ConfigDict(frozen=True)

    attr: str                        # key in the parent payload, e.g. "currency"
    module: str                      # registry name owning the nested entity
    many: bool = False               # attr is a list of payloads
    parent_fk: str | None = None     # parent column receiving the child LOCAL id
    parent_zoho_fk: str | None = None  # parent column receiving the child zoho_id


class GlobalSyncDefaults(BaseModel):
    """Layer-1/2 defaults. Every knob a module may override lives here."""

    enabled: bool = True
    direction: SyncDirection = SyncDirection.INBOUND
    strategy: SyncStrategyName = SyncStrategyName.INCREMENTAL
    # N+1 handling: fetch the full record before upserting?
    detail_required: bool = False
    # inline  — fetch details in the same task (respects wait_between_calls)
    # queued  — fan out one Celery task per record (max parallel throughput)
    detail_dispatch: Literal["inline", "queued"] = "inline"
    # Two-phase apply for detail_required modules: write the INDEX row first,
    # then fetch /{endpoint}/{id} and upsert the detail over it.
    #
    # The row therefore exists as soon as it is listed, which matters because
    # (a) a detail call that fails, is rate-limited or is queued no longer
    # leaves a hole where a record should be, and (b) anything resolving a
    # reference to this record finds it immediately. The apply gate makes the
    # second write safe and the steady state free: the detail payload outranks
    # the index one (provenance), and once a row already holds the detail
    # document of the listed version, neither phase spends a call or a write.
    index_then_detail: bool = False
    batch_size: int = Field(default=200, ge=1, le=200)   # Zoho page cap is 200
    # Above this many records an incremental run escalates to a full run
    full_sync_threshold: int = 25_000
    sync_interval_minutes: int = 15
    wait_between_calls: float = Field(default=0.0, ge=0.0)
    retry_limit: int = 5
    # Incremental support: Zoho query param + sort column (None = no support,
    # incremental silently degrades to a full run)
    modified_since_param: str | None = "last_modified_time"
    sort_column: str | None = "last_modified_time"
    soft_delete_missing: bool = False   # full sync soft-deletes vanished rows
    # ── "When to stop" — every run is a bounded slice (0 = no limit) ────────
    # A run that hits a budget ends YIELDED, keeps its page/cursor, and the
    # planner resumes it on the next tick (docs/zoho-sync-implementation/
    # apply-gate.md §4).
    max_run_seconds: int = Field(default=240, ge=0, le=3600)
    max_pages_per_run: int = Field(default=0, ge=0)
    max_records_per_run: int = Field(default=0, ge=0)
    # Planner: include this module in the weekly full-reconcile lane.
    weekly_full_enabled: bool = True
    # Reference resolution (redesign §4.1 step 5): the ceiling on UNPLANNED
    # detail calls one run may spend chasing masters a document names. "Fetch
    # it and insert it first" is right per record and ruinous per page — a page
    # of 200 documents naming 200 unsynced contacts would trip the rate limiter
    # and spend the run's whole quota on references. Over budget, FETCH
    # degrades to STUB: the row still links, to a provisional entity the owning
    # module's own sync fills in. 0 = never fetch (everything degrades).
    max_reference_fetches_per_run: int = Field(default=50, ge=0)
    # Apply gate: payload keys (glob, any depth) ignored by the no-op hash.
    hash_volatile_keys: list[str] = Field(
        default_factory=lambda: ["*_formatted", "page_context", "instrumentation"]
    )


class ModuleSyncConfig(GlobalSyncDefaults):
    """The fully-resolved, validated configuration the engine executes."""

    module: str                       # registry key, e.g. "organizations"
    endpoint: str                     # list endpoint, e.g. "/organizations"
    zoho_id_attr: str                 # PK attribute in Zoho payloads
    api: Literal["books", "inventory"] = "books"   # which Zoho product serves the endpoint
    # False for list endpoints that return everything in one response WITHOUT
    # page_context (e.g. /settings/currencies) — the transport would otherwise
    # treat the missing page_context as a contract violation.
    paginated: bool = True
    detail_endpoint: str | None = None  # default: f"{endpoint}/{zoho_id}"
    list_params: dict[str, Any] = Field(default_factory=dict)
    field_map: list[FieldMapping] = Field(default_factory=list)
    nested: list[NestedEntityRule] = Field(default_factory=list)
    #: How the result is STORED (the part SAP reuses verbatim): canonical table,
    #: match key, whether gate state lives on the crosswalk. The default has
    #: ``crosswalk=False``, so a module that declares nothing keeps today's
    #: in-place mirror behaviour exactly.
    contract: SyncContract = SyncContract()

    @field_validator("endpoint")
    @classmethod
    def _leading_slash(cls, v: str) -> str:
        return v if v.startswith("/") else f"/{v}"

    def detail_path(self, zoho_id: str) -> str:
        base = self.detail_endpoint or self.endpoint
        return f"{base.rstrip('/')}/{zoho_id}"


def _env_defaults() -> GlobalSyncDefaults:
    """Layer 2: fleet-wide overrides sourced from app settings (env vars)."""
    return GlobalSyncDefaults(
        batch_size=settings.ZOHO_SYNC_BATCH_SIZE,
        full_sync_threshold=settings.ZOHO_SYNC_FULL_THRESHOLD,
        sync_interval_minutes=settings.ZOHO_SYNC_INTERVAL_MINUTES,
        wait_between_calls=settings.ZOHO_SYNC_WAIT_BETWEEN_CALLS,
        retry_limit=settings.ZOHO_SYNC_RETRY_LIMIT,
        max_run_seconds=settings.ZOHO_SYNC_MAX_RUN_SECONDS,
        max_pages_per_run=settings.ZOHO_SYNC_MAX_PAGES_PER_RUN,
        max_records_per_run=settings.ZOHO_SYNC_MAX_RECORDS_PER_RUN,
        hash_volatile_keys=[
            key.strip() for key in settings.ZOHO_SYNC_HASH_VOLATILE_KEYS.split(",") if key.strip()
        ],
    )


# Materialised once; import this wherever the effective defaults are needed.
sync_defaults = _env_defaults()


def resolve_module_config(**overrides: Any) -> ModuleSyncConfig:
    """Merge global defaults with a module's declaration (module wins).

    Modules pass ONLY the knobs they care about; everything else inherits
    from ``sync_defaults`` — the hierarchical merge the legacy Laravel
    zoho-modules.php provided, now validated by Pydantic at import time.
    """
    merged: dict[str, Any] = {**sync_defaults.model_dump(), **overrides}
    return ModuleSyncConfig(**merged)
