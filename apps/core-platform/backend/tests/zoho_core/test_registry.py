"""Package-by-feature registry: discovery, startup validation, dependency rule."""

import pathlib
import re

import pytest
from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.mixins import IntPKMixin
from app.database.soft_delete import SoftDeleteFilteredMixin
from app.modules.zoho.sync.config import FieldMapping, NestedEntityRule, resolve_module_config
from app.modules.zoho.sync.mixins import ZohoIdentityMixin, ZohoMirrorMixin
from app.modules.zoho.sync.registry import (
    _ADAPTER_PACKAGES,
    RegistryError,
    SyncRegistry,
    ZohoModuleDefinition,
    sync_registry,
)


class _GoodMirror(IntPKMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "_test_registry_good"
    name: Mapped[str | None] = mapped_column(String(50))
    __table_args__ = (Index("uq__test_registry_good_live", "zoho_id", unique=True,
                            postgresql_where=text("deleted_at IS NULL")),)


class _NoMirror(IntPKMixin, SoftDeleteFilteredMixin, ZohoIdentityMixin, Base):
    __tablename__ = "_test_registry_no_mirror"
    __table_args__ = (Index("uq__test_registry_no_mirror_live", "zoho_id", unique=True),)


class _NoUniqueIndex(IntPKMixin, SoftDeleteFilteredMixin, ZohoMirrorMixin, ZohoIdentityMixin, Base):
    __tablename__ = "_test_registry_no_unique"


# Keep the throwaway tables out of the application metadata (alembic, create_all).
for _model in (_GoodMirror, _NoMirror, _NoUniqueIndex):
    Base.metadata.remove(_model.__table__)


def spec(module, model, **overrides):
    overrides.setdefault("endpoint", f"/{module}")
    config = resolve_module_config(module=module, zoho_id_attr="id", **overrides)
    return ZohoModuleDefinition(config=config, model=model)


def validate(*definitions):
    registry = SyncRegistry()
    for definition in definitions:
        registry.register(definition)
    registry.validate()


def test_the_shipped_modules_are_discovered_and_valid():
    sync_registry.validate()
    assert {"organizations", "currencies", "taxes"} <= set(sync_registry.names())
    assert all(package.endswith(".zoho") for package in _ADAPTER_PACKAGES)


def test_a_valid_spec_passes():
    validate(spec("good", _GoodMirror, field_map=[FieldMapping(zoho="name", local="name")]))


@pytest.mark.parametrize(
    ("definition", "problem"),
    [
        (spec("typo", _GoodMirror, field_map=[FieldMapping(zoho="name", local="nmae")]), "unknown columns ['nmae']"),
        (spec("legacy", _NoMirror), "lacks apply-gate columns"),
        (spec("dupes", _NoUniqueIndex), "needs a unique (partial) index on (tenant_id, zoho_id)"),
        (spec("parent", _GoodMirror, nested=[NestedEntityRule(attr="currency", module="nope")]),
         "unregistered module 'nope'"),
    ],
)
def test_broken_specs_fail_at_startup(definition, problem):
    with pytest.raises(RegistryError, match=re.escape(problem)):
        validate(definition)


def test_two_modules_cannot_claim_one_endpoint():
    with pytest.raises(RegistryError, match="already served"):
        validate(spec("a", _GoodMirror), spec("b", _GoodMirror, endpoint="/a"))


def test_platform_code_never_imports_a_feature():
    """Dependency rule (architecture §6.2): app.modules.zoho is entity-agnostic;
    features are reached only through the registry's string list."""
    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules" / "zoho"
    features = {package.split(".")[2] for package in _ADAPTER_PACKAGES}
    pattern = re.compile(r"^\s*(from|import)\s+app\.modules\.(" + "|".join(features) + r")\b", re.M)
    offenders = [str(path.relative_to(root)) for path in root.rglob("*.py") if pattern.search(path.read_text())]
    assert offenders == []
