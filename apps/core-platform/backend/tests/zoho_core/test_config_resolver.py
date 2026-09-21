"""Runtime per-module config overrides (control/config.py)."""

import pytest
from sqlalchemy import select

from app.modules.system.model import SettingAuditLog
from app.modules.zoho.control.config import KNOBS, ConfigError, ConfigResolver, zoho_config
from app.modules.zoho.sync.config import SyncStrategyName
from app.modules.zoho.sync.registry import sync_registry


@pytest.fixture
def orgs():
    return sync_registry.get("organizations")


# ── knob parsing (pure) ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("knob", "raw", "value"),
    [
        ("enabled", "false", False),
        ("enabled", True, True),
        ("sync_interval_minutes", "30", 30),
        ("wait_between_calls", 0.5, 0.5),
        ("strategy", "incremental", "incremental"),
        ("hash_volatile_keys", '["*_formatted", "etag"]', ["*_formatted", "etag"]),
    ],
)
def test_knobs_coerce(knob, raw, value):
    assert KNOBS[knob].coerce(raw) == value


@pytest.mark.parametrize(
    ("knob", "raw"),
    [
        ("sync_interval_minutes", 0),           # below the floor
        ("batch_size", 500),                    # Zoho caps pages at 200
        ("max_run_seconds", 600),               # must stay under Celery's soft limit
        ("strategy", "sometimes"),
        ("enabled", "maybe"),
        ("sync_interval_minutes", True),        # a bool is not an int here
        ("hash_volatile_keys", '["", 3]'),
    ],
)
def test_knobs_refuse_bad_values(knob, raw):
    with pytest.raises(ValueError):
        KNOBS[knob].coerce(raw)


# ── resolver against Postgres + Redis ───────────────────────────────────────

async def test_override_applies_and_is_audited(db, redis_available, orgs):
    assert (await zoho_config.effective(db, orgs)) is orgs.config          # no overrides → same object

    await zoho_config.set(db, orgs, "sync_interval_minutes", 30, actor="7", ip_address="10.0.0.1")
    await zoho_config.set(db, orgs, "strategy", "index", actor="7")
    cfg = await zoho_config.effective(db, orgs)
    assert cfg.sync_interval_minutes == 30 and cfg.strategy is SyncStrategyName.INDEX
    assert cfg.endpoint == orgs.config.endpoint                              # identity untouched

    described = await zoho_config.describe(db, orgs)
    assert described["sync_interval_minutes"] == {**described["sync_interval_minutes"],
                                                  "value": 30, "layer": "override", "declared": 360}
    assert described["batch_size"]["layer"] == "default"

    audit = (await db.scalars(select(SettingAuditLog))).all()
    assert {a.definition_key for a in audit} == {"zoho.module.organizations.sync_interval_minutes",
                                                 "zoho.module.organizations.strategy"}


async def test_refusals_do_not_persist(db, redis_available, orgs):
    with pytest.raises(ConfigError):
        await zoho_config.set(db, orgs, "endpoint", "/evil", actor="7")         # identity is not a knob
    with pytest.raises(ConfigError):
        await zoho_config.set(db, orgs, "batch_size", 1000, actor="7")
    assert await zoho_config.overrides(db) == {}


async def test_clear_restores_the_declared_value(db, redis_available, orgs):
    await zoho_config.set(db, orgs, "sync_interval_minutes", 30, actor="7")
    assert await zoho_config.clear(db, orgs, "sync_interval_minutes", actor="7") is True
    assert (await zoho_config.effective(db, orgs)).sync_interval_minutes == 360
    assert await zoho_config.clear(db, orgs, "sync_interval_minutes", actor="7") is False
    cleared = (await db.scalars(
        select(SettingAuditLog).where(SettingAuditLog.new_value == "(override removed)")
    )).all()
    assert len(cleared) == 1


async def test_other_processes_see_a_change_via_the_version_counter(db, redis_available, orgs):
    other = ConfigResolver(cache_seconds=0)                                  # "another worker"
    assert await other.overrides(db) == {}
    await zoho_config.set(db, orgs, "max_pages_per_run", 5, actor="7")
    assert (await other.overrides(db))["organizations"]["max_pages_per_run"] == 5


async def test_a_corrupt_stored_value_is_ignored_not_fatal(db, redis_available, orgs):
    from app.modules.system.service import system_settings_service

    await system_settings_service.set_setting(
        db, "zoho.module.organizations.batch_size", "9999", updated_by="manual-sql"
    )
    await db.commit()
    zoho_config.invalidate()
    assert (await zoho_config.effective(db, orgs)).batch_size == orgs.config.batch_size
