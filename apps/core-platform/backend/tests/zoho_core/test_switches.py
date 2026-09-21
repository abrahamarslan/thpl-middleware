"""Engine switches — refusal rules, persistence, mirror rebuild, auth pause."""

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.zoho.control.switches import (
    EngineSwitches,
    SwitchState,
    ZohoEngineDisabled,
    _AUTH_PAUSE_KEY,
    _MIRROR_KEY,
)


# ── pure refusal rules ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("state", "direction", "module", "interactive", "expected"),
    [
        (SwitchState(), "pull", "items", False, None),
        (SwitchState(engine_paused=True), "pull", "items", False, "engine_paused"),
        (SwitchState(engine_paused=True), "pull", "items", True, None),          # users still served
        (SwitchState(pull_enabled=False), "pull", "items", False, "pull_disabled"),
        (SwitchState(pull_enabled=False), "push", "items", False, None),
        (SwitchState(push_enabled=False), "push", "items", True, "push_disabled"),  # a push is a push
        (SwitchState(paused_modules=frozenset({"items"})), "pull", "items", False, "module_paused:items"),
        (SwitchState(paused_modules=frozenset({"items"})), "pull", "contacts", False, None),
        (SwitchState(auth_paused=True), "pull", "items", True, "auth_paused"),    # nothing gets through
    ],
)
def test_refusal_rules(state, direction, module, interactive, expected):
    assert state.refusal(direction=direction, module=module, interactive=interactive) == expected


# ── storage ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def switches(db, redis_available):
    await redis_available.delete(_MIRROR_KEY, _AUTH_PAUSE_KEY)
    s = EngineSwitches(
        redis=redis_available,
        session_factory=async_sessionmaker(db.bind, expire_on_commit=False),
        cache_seconds=0,
    )
    yield s
    await redis_available.delete(_MIRROR_KEY, _AUTH_PAUSE_KEY)


async def test_defaults_when_nothing_is_configured(switches):
    state = await switches.snapshot()
    assert state.engine_paused is False and state.pull_enabled is True
    assert state.push_enabled is True and state.webhooks_enabled is False


async def test_set_persists_audits_and_mirrors(switches, db, redis_available):
    state = await switches.set(db, "engine_paused", True, actor="7")
    await db.commit()
    assert state.engine_paused is True

    mirror = await redis_available.hgetall(_MIRROR_KEY)
    assert json.loads(mirror["engine_paused"]) is True

    from sqlalchemy import text

    audit = (await db.execute(text(
        "SELECT new_value, changed_by FROM setting_audit_logs "
        "WHERE definition_key = 'zoho.control.engine_paused' ORDER BY id DESC LIMIT 1"
    ))).first()
    assert audit is not None and audit.changed_by == "7"


async def test_mirror_is_rebuilt_from_postgres_after_redis_loss(switches, db, redis_available):
    await switches.set(db, "paused_modules", ["items", "contacts"], actor="1")
    await db.commit()

    await redis_available.delete(_MIRROR_KEY)            # eviction / restart
    state = await switches.snapshot()
    assert state.paused_modules == frozenset({"items", "contacts"})
    assert state.source == "database"
    assert await redis_available.hget(_MIRROR_KEY, "loaded") == "1"


async def test_check_raises_engine_disabled(switches, db):
    await switches.set(db, "pull_enabled", False, actor="1")
    await db.commit()
    with pytest.raises(ZohoEngineDisabled) as excinfo:
        await switches.check(direction="pull", module="items", interactive=False)
    assert excinfo.value.reason == "switch:pull_disabled"


async def test_auth_pause_blocks_everything_until_cleared(switches):
    await switches.set_auth_paused("refresh_token_invalid_code")
    with pytest.raises(ZohoEngineDisabled):
        await switches.check(direction="pull", module=None, interactive=True)

    await switches.clear_auth_paused()
    await switches.check(direction="pull", module=None, interactive=True)   # no raise


async def test_invalid_switch_values_are_rejected(switches, db):
    with pytest.raises(ValueError):
        await switches.set(db, "engine_paused", "yes", actor="1")
    with pytest.raises(ValueError):
        await switches.set(db, "not_a_switch", True, actor="1")
