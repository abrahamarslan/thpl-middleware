"""Sync module registry — the runtime catalogue of Zoho entity modules.

Each entity module (organizations, contacts, taxes, ...) self-registers a
``ZohoModuleDefinition`` at import time:

    # app/modules/zoho/organizations/__init__.py
    sync_registry.register(ZohoModuleDefinition(config=..., model=...))

``autodiscover()`` imports every entity package so registrations run before
the engine, the Celery beat dispatcher or the admin API enumerate modules.
Add new modules to ``_ENTITY_PACKAGES`` — one line per module, mirroring how
routers register once in app/router.py.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

import structlog

from app.common.exception.errors import NotFoundError
from app.modules.zoho.sync.config import ModuleSyncConfig

logger = structlog.get_logger("app.zoho.sync.registry")

#: Packages imported by autodiscover(); each must register itself on import.
_ENTITY_PACKAGES = [
    "app.modules.zoho.organizations",
]

#: Hook signatures. Both receive (payload, values) and may amend `values`;
#: pre-hooks run before the upsert, post-hooks after flush (row available).
PreUpsertHook = Callable[[dict, dict[str, Any]], dict[str, Any]]
PostUpsertHook = Callable[[Any, dict], Awaitable[None]]


@dataclass
class ZohoModuleDefinition:
    """Everything the engine needs to sync one entity type."""

    config: ModuleSyncConfig
    model: type                      # SQLAlchemy model with ZohoEntityMixin
    pre_upsert: PreUpsertHook | None = None
    post_upsert: PostUpsertHook | None = None
    #: Extra searchable summary shown by the admin API.
    tags: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.config.module


class SyncRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ZohoModuleDefinition] = {}
        self._discovered = False

    def register(self, definition: ZohoModuleDefinition) -> ZohoModuleDefinition:
        name = definition.name
        if name in self._modules:
            # Idempotent re-registration (test re-imports, dev reload)
            logger.debug("sync_module_reregistered", module=name)
        self._modules[name] = definition
        logger.info(
            "sync_module_registered",
            module=name,
            endpoint=definition.config.endpoint,
            strategy=definition.config.strategy.value,
            direction=definition.config.direction.value,
        )
        return definition

    def get(self, name: str) -> ZohoModuleDefinition:
        self.autodiscover()
        try:
            return self._modules[name]
        except KeyError:
            raise NotFoundError(f"Unknown Zoho sync module '{name}'") from None

    def all(self) -> list[ZohoModuleDefinition]:
        self.autodiscover()
        return list(self._modules.values())

    def names(self) -> list[str]:
        self.autodiscover()
        return sorted(self._modules)

    def autodiscover(self) -> None:
        """Import every entity package once so registrations execute."""
        if self._discovered:
            return
        self._discovered = True
        for package in _ENTITY_PACKAGES:
            try:
                import_module(package)
            except Exception:  # pragma: no cover — a broken module must be loud
                logger.error("sync_module_import_failed", package=package, exc_info=True)
                raise


sync_registry = SyncRegistry()
