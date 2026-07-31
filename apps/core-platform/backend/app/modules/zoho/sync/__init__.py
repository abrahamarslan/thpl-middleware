"""Zoho Sync Engine — distributed, config-driven, bidirectional MDM replication.

This package turns the low-level Zoho core client (app/modules/zoho/core)
into a full Master-Data-Management pipeline:

    config.py    hierarchical configuration (global defaults + per-module
                 overrides + declarative Zoho-attribute -> local-column maps)
    mapper.py    the field-mapping engine (dotted paths, typed transforms,
                 inbound + outbound payload building)
    mixins.py    ZohoEntityMixin — the strict schema every mirrored entity
                 table implements (identifiers, sync columns, status flags,
                 hstore custom fields, JSONB metadata)
    models.py    observability tables: zoho_sync_stats (table-level) and
                 zoho_queue_logs (row-level queue journal)
    registry.py  the module registry — each entity module self-registers a
                 ZohoModuleDefinition (config + model + hooks)
    engine.py    the sync strategies (full / incremental / index), N+1
                 detail-fetch orchestration and nested-entity FK resolution
    outbox.py    local -> Zoho pushes (create / update / delete) with the
                 transactional-outbox pattern via zoho_queue_logs

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
from app.modules.zoho.sync.mixins import SyncStatus, ZohoEntityMixin
from app.modules.zoho.sync.registry import ZohoModuleDefinition, sync_registry

__all__ = [
    "FieldMapping",
    "ModuleSyncConfig",
    "NestedEntityRule",
    "SyncDirection",
    "SyncStrategyName",
    "SyncStatus",
    "ZohoEntityMixin",
    "ZohoModuleDefinition",
    "sync_defaults",
    "sync_registry",
]
