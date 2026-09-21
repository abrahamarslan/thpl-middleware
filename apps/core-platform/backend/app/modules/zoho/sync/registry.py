"""Sync module registry — the runtime catalogue of Zoho entity modules.

Package-by-feature (docs/zoho-sync-implementation/package-by-feature.md): each
feature owns its Zoho adapter in ``app/modules/<feature>/zoho/`` and
self-registers a ``ZohoModuleDefinition`` when that package is imported:

    # app/modules/organizations/zoho/__init__.py
    sync_registry.register(SPEC)

``autodiscover()`` imports every adapter package listed in
``_ADAPTER_PACKAGES`` (by string — the platform never imports a feature
directly), then :meth:`SyncRegistry.validate` checks every spec against its
model. A broken spec fails the process at startup, not at 03:00 in a worker.
Add new modules to ``_ADAPTER_PACKAGES`` — one line per module, mirroring how
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

#: Adapter packages imported by autodiscover(); each registers itself on import.
#: Order matters only for readability — dependencies are declared by specs.
_ADAPTER_PACKAGES = [
    "app.modules.organizations.zoho",
    "app.modules.zoho_currencies.zoho",
    "app.modules.taxes.zoho",
    "app.modules.locations.zoho",
    "app.modules.zoho_users.zoho",
]
_ENTITY_PACKAGES = _ADAPTER_PACKAGES      # v1 name, kept for existing references

#: Columns the apply gate reads/writes on every mirror table (ZohoIdentityMixin + ZohoMirrorMixin).
_GATE_COLUMNS = (
    "zoho_id", "deleted_at", "zoho_raw", "zoho_raw_hash", "zoho_raw_synced_at",
    "zoho_last_modified_time", "synced_at", "sync_source", "sync_version", "remote_deleted_at",
)


class RegistryError(RuntimeError):
    """A module spec is inconsistent with its model or with other specs."""

#: Hook signatures. Both receive (payload, values) and may amend `values`;
#: pre-hooks run before the upsert, post-hooks after flush (row available).
PreUpsertHook = Callable[[dict, dict[str, Any]], dict[str, Any]]
PostUpsertHook = Callable[[Any, dict], Awaitable[None]]


@dataclass
class ZohoModuleDefinition:
    """Everything the engine needs to sync one entity type."""

    config: ModuleSyncConfig
    model: type                      # SQLAlchemy model with the Identity + Mirror columns
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
        """Import every adapter package once, then validate all specs."""
        if self._discovered:
            return
        self._discovered = True
        for package in _ADAPTER_PACKAGES:
            try:
                import_module(package)
            except Exception:  # pragma: no cover — a broken module must be loud
                logger.error("sync_module_import_failed", package=package, exc_info=True)
                raise
        self.validate()

    def validate(self) -> None:
        """Fail fast on specs the engine could not execute safely.

        Checks (each one a production incident class in v1):
          * every field-map ``local`` is a column of the model;
          * the model carries the apply-gate columns (Identity + Mirror mixins);
          * the model declares a UNIQUE index on ``zoho_id`` (the identity key);
          * nested rules point at registered modules;
          * one endpoint is served by one module only.
        """
        problems: list[str] = []
        endpoints: dict[tuple[str, str], str] = {}
        for name, defn in self._modules.items():
            cfg, model = defn.config, defn.model
            table = getattr(model, "__table__", None)
            if table is None:
                problems.append(f"{name}: model {model!r} is not a mapped table")
                continue
            columns = set(table.columns.keys())
            contract = cfg.contract

            if contract.crosswalk:
                # Identity and gate state live in sync.sync_records, so the
                # entity table must NOT be asked for mirror columns. What must
                # hold instead: the declared entity_table is this model's, and
                # every match key is a real column — a bad match key silently
                # merges unrelated records, which is the worst failure here.
                if contract.entity_table and contract.entity_table != table.fullname:
                    problems.append(
                        f"{name}: contract.entity_table '{contract.entity_table}' is not "
                        f"the model's table '{table.fullname}'"
                    )
                unknown_match = sorted(set(contract.match_on) - columns)
                if unknown_match:
                    problems.append(f"{name}: contract.match_on names unknown columns {unknown_match}")
                unknown_owned = sorted(contract.owned_fields - columns)
                if unknown_owned:
                    problems.append(f"{name}: contract.owned_fields names unknown columns {unknown_owned}")
            else:
                missing_gate = [c for c in _GATE_COLUMNS if c not in columns]
                if missing_gate:
                    problems.append(f"{name}: {table.name} lacks apply-gate columns {missing_gate} "
                                    "(compose ZohoIdentityMixin + ZohoMirrorMixin)")
                if not any(
                    index.unique and [c.name for c in index.columns] in (["zoho_id"], ["tenant_id", "zoho_id"])
                    for index in table.indexes
                ):
                    problems.append(f"{name}: {table.name} needs a unique (partial) index on (tenant_id, zoho_id)")

            unknown = sorted({m.local for m in cfg.field_map} - columns)
            if unknown:
                problems.append(f"{name}: field map targets unknown columns {unknown}")
            for rule in cfg.nested:
                if rule.module not in self._modules:
                    problems.append(f"{name}: nested rule '{rule.attr}' → unregistered module '{rule.module}'")
            for reference in contract.references:
                if reference.module not in self._modules:
                    problems.append(f"{name}: reference '{reference.attr}' → unregistered "
                                    f"module '{reference.module}'")
                for column in (reference.fk, reference.external_fk):
                    if column and column not in columns:
                        problems.append(f"{name}: reference '{reference.attr}' targets "
                                        f"unknown column '{column}'")
            key = (cfg.api, cfg.endpoint)
            if key in endpoints and endpoints[key] != name:
                problems.append(f"{name}: endpoint {cfg.endpoint} already served by '{endpoints[key]}'")
            endpoints[key] = name
        if problems:
            for problem in problems:
                logger.critical("zoho.registry.invalid_spec", problem=problem)
            raise RegistryError("invalid Zoho module specs:\n  " + "\n  ".join(problems))


sync_registry = SyncRegistry()
