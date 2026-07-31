"""Hierarchical configuration — merge semantics and validation."""

import pytest
from pydantic import ValidationError

from app.modules.zoho.sync.config import (
    FieldMapping,
    NestedEntityRule,
    SyncDirection,
    SyncStrategyName,
    resolve_module_config,
    sync_defaults,
)


def test_module_inherits_global_defaults():
    cfg = resolve_module_config(module="things", endpoint="/things", zoho_id_attr="thing_id")
    assert cfg.batch_size == sync_defaults.batch_size
    assert cfg.strategy == sync_defaults.strategy
    assert cfg.retry_limit == sync_defaults.retry_limit
    assert cfg.direction == SyncDirection.INBOUND
    assert cfg.enabled is True


def test_module_overrides_win_over_defaults():
    cfg = resolve_module_config(
        module="things", endpoint="things", zoho_id_attr="thing_id",
        strategy=SyncStrategyName.INDEX, batch_size=50,
        wait_between_calls=1.5, direction=SyncDirection.BIDIRECTIONAL,
    )
    assert cfg.strategy is SyncStrategyName.INDEX
    assert cfg.batch_size == 50
    assert cfg.wait_between_calls == 1.5
    # Untouched knobs still inherit
    assert cfg.sync_interval_minutes == sync_defaults.sync_interval_minutes
    # Endpoint normalised to a leading slash
    assert cfg.endpoint == "/things"


def test_detail_path_building():
    cfg = resolve_module_config(module="things", endpoint="/things", zoho_id_attr="thing_id")
    assert cfg.detail_path("123") == "/things/123"

    cfg2 = resolve_module_config(
        module="things", endpoint="/things", zoho_id_attr="thing_id",
        detail_endpoint="/things/details",
    )
    assert cfg2.detail_path("123") == "/things/details/123"


def test_batch_size_capped_at_zoho_page_limit():
    with pytest.raises(ValidationError):
        resolve_module_config(module="x", endpoint="/x", zoho_id_attr="id", batch_size=500)


def test_blank_field_mapping_rejected():
    with pytest.raises(ValidationError):
        FieldMapping(zoho="  ", local="name")


def test_nested_rule_shape():
    rule = NestedEntityRule(attr="currency", module="currencies", parent_fk="currency_local_id")
    assert rule.many is False
    assert rule.parent_zoho_fk is None
