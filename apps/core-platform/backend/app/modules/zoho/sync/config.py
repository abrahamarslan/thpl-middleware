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


class FieldMapping(BaseModel):
    """One Zoho-attribute -> local-column mapping.

    ``zoho`` is a dotted path into the payload (``"address.city"``).
    ``transform`` names a registered coercion in mapper.TRANSFORMS.
    ``default`` is applied only when the key is present-but-null or when
    ``apply_default_when_missing`` is set; otherwise missing keys are skipped
    entirely so a partial payload can never null-out existing data.
    """

    model_config = ConfigDict(frozen=True)

    zoho: str
    local: str
    transform: str | None = None
    default: Any = None
    apply_default_when_missing: bool = False
    # Outbound behaviour
    outbound: bool = True                 # include in payloads pushed to Zoho
    outbound_key: str | None = None       # override the Zoho key on writes

    @field_validator("zoho", "local")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("mapping paths must not be blank")
        return v


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


class ModuleSyncConfig(GlobalSyncDefaults):
    """The fully-resolved, validated configuration the engine executes."""

    module: str                       # registry key, e.g. "organizations"
    endpoint: str                     # list endpoint, e.g. "/organizations"
    zoho_id_attr: str                 # PK attribute in Zoho payloads
    detail_endpoint: str | None = None  # default: f"{endpoint}/{zoho_id}"
    list_params: dict[str, Any] = Field(default_factory=dict)
    field_map: list[FieldMapping] = Field(default_factory=list)
    nested: list[NestedEntityRule] = Field(default_factory=list)

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
