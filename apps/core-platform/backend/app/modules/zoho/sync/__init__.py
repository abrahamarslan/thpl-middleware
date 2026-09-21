"""Zoho Sync Engine — distributed, config-driven, bidirectional MDM replication.

This package turns the low-level Zoho core client (app/modules/zoho/core)
into a full Master-Data-Management pipeline:

    config.py    hierarchical configuration (global defaults + per-module
                 overrides + declarative Zoho-attribute -> local-column maps)
    mapper.py    the field-mapping engine (dotted paths, typed transforms,
                 inbound + outbound payload building)
    mixins.py    Identity / Mirror / Pushable / Approval / WarehouseScoped /
                 Child column mixins (compose per capability)
    models.py    observability tables: zoho_sync_stats (table-level) and
                 zoho_queue_logs (row-level queue journal)
    registry.py  the module registry — each entity module self-registers a
                 ZohoModuleDefinition (config + model + hooks)
    engine.py    the sync strategies (full / incremental / index), N+1
                 detail-fetch orchestration and nested-entity FK resolution
    apply.py     the apply gate (fence, hash no-op, provenance, tombstones)

Pushes (local -> Zoho) return with outbox v2 (Phase 8); the v1 outbox was
retired with the v1 organizations table.

Celery drivers live in app/tasks/zoho_sync.py; the admin API in
app/modules/zoho/sync/api.py (mounted under /api/zoho/sync-engine).
"""

from app.modules.zoho.sync.config import (
    FieldMapping,
    ModuleSyncConfig,
    NestedEntityRule,
    SyncDirection,
    SyncStrategyName,
    sync_defaults,
)
from app.modules.zoho.sync.mixins import SyncStatus
from app.modules.zoho.sync.registry import ZohoModuleDefinition, sync_registry

__all__ = [
    "FieldMapping",
    "ModuleSyncConfig",
    "NestedEntityRule",
    "SyncDirection",
    "SyncStrategyName",
    "SyncStatus",
    "ZohoModuleDefinition",
    "sync_defaults",
    "sync_registry",
]
