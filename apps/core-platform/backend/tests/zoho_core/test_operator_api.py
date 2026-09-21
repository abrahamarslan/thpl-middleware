"""Operator API — authorisation, health, switches, record history, metrics."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.conf import settings
from app.database.db import get_db
from app.main import app
from app.modules.users.deps import get_current_user
from app.modules.zoho.admin.deps import require_zoho_operator
from app.modules.zoho.control.metrics import QUOTA_STATE, QUOTA_USED, SWITCH, apply_snapshot


# ── authorisation ───────────────────────────────────────────────────────────

async def test_operator_allow_list(monkeypatch):
    from app.common.exception.errors import ForbiddenError

    monkeypatch.setattr(settings, "ZOHO_OPERATOR_EMAILS", "ops@tarrinahealth.com")
    monkeypatch.setattr(settings, "DEBUG", False)
    assert await require_zoho_operator(SimpleNamespace(id=1, email="OPS@tarrinahealth.com"))
    with pytest.raises(ForbiddenError):
        await require_zoho_operator(SimpleNamespace(id=2, email="someone@else.com"))


async def test_empty_allow_list_is_closed_in_production(monkeypatch):
    from app.common.exception.errors import ForbiddenError

    monkeypatch.setattr(settings, "ZOHO_OPERATOR_EMAILS", "")
    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(ForbiddenError):
        await require_zoho_operator(SimpleNamespace(id=1, email="anyone@x.com"))

    monkeypatch.setattr(settings, "DEBUG", True)
    assert await require_zoho_operator(SimpleNamespace(id=1, email="anyone@x.com"))


def test_admin_routes_are_mounted():
    paths = app.openapi()["paths"]
    for path in ("/api/zoho/admin/health", "/api/zoho/admin/switches/{name}",
                 "/api/zoho/admin/runs", "/api/zoho/admin/records/{module}/{ref}/events",
                 "/api/zoho/admin/retention", "/api/zoho/admin/modules/{module}/pause"):
        assert path in paths, path


def test_admin_routes_reject_non_operators(monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_OPERATOR_EMAILS", "ops@x.com")
    monkeypatch.setattr(settings, "DEBUG", False)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=9, email="user@x.com")
    try:
        response = TestClient(app).get("/api/zoho/admin/switches")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ── end-to-end against the scratch services ─────────────────────────────────
# httpx.ASGITransport keeps requests on the test's own event loop, so the
# route can share the `db` fixture's session (TestClient would run the app on
# another loop and asyncpg would refuse the connection — ERRORS E06).

@pytest.fixture
async def operator_client(db, redis_available):
    import httpx

    operator = SimpleNamespace(id=1, email="ops@x.com")

    async def _db():
        yield db

    app.dependency_overrides[require_zoho_operator] = lambda: operator
    app.dependency_overrides[get_db] = _db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_switch_change_is_audited_and_visible(operator_client, db):
    from app.modules.zoho.control.switches import zoho_switches

    response = await operator_client.put(
        "/api/zoho/admin/switches/engine_paused",
        json={"value": True, "reason": "month-end close"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["engine_paused"] is True

    from sqlalchemy import text

    activity = (await db.execute(text(
        "SELECT action FROM activity_logs WHERE action = 'zoho_switch_changed'"
    ))).first()
    assert activity is not None

    bad = await operator_client.put("/api/zoho/admin/switches/nope", json={"value": True, "reason": "typo test"})
    assert bad.status_code == 404

    await operator_client.put("/api/zoho/admin/switches/engine_paused", json={"value": False, "reason": "done"})
    zoho_switches.invalidate()


async def test_record_history_endpoint(operator_client, db):
    from app.modules.zoho.sync.engine import ZohoSyncEngine
    from tests.zoho_core.test_sync_events import ORG, client_for

    await ZohoSyncEngine(db, client_for(ORG), run_id=uuid.uuid4()).run("organizations", "full")
    await db.commit()

    response = await operator_client.get("/api/zoho/admin/records/organizations/10229182/events?by=zoho")
    assert response.status_code == 200, response.text
    events = response.json()["data"]
    assert [e["event_type"] for e in events] == ["inserted"]
    assert events[0]["zoho_id"] == "10229182"

    unknown = await operator_client.get("/api/zoho/admin/records/not_a_module/1/events")
    assert unknown.status_code == 404


async def test_health_endpoint_aggregates_the_control_plane(operator_client):
    response = await operator_client.get("/api/zoho/admin/health")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert {"governor", "switches", "token", "breakers", "running_runs"} <= data.keys()
    assert data["governor"]["daily_hard_limit"] == settings.ZOHO_DAILY_HARD_LIMIT


# ── metrics mapping (pure) ──────────────────────────────────────────────────

def test_snapshot_maps_onto_gauges():
    tick = datetime.now(UTC) - timedelta(seconds=30)
    apply_snapshot({
        "planner_last_tick": tick.isoformat(),
        "planner": {"running": 1},
        "governor": {"pool": "zoho", "used": 1234, "remaining": 43766, "daily_hard_limit": 45000,
                     "state": "conserve", "background_allowance": 9000, "rate_tokens": 7.5, "inflight": 2},
        "switches": {"engine_paused": True, "pull_enabled": True, "push_enabled": False,
                     "auth_paused": False, "paused_modules": ["items"]},
        "token": {"token_ttl_seconds": 3000, "refreshes_in_window": 1},
    })
    assert QUOTA_USED.labels("zoho")._value.get() == 1234
    assert QUOTA_STATE.labels("zoho")._value.get() == 1
    assert SWITCH.labels("engine_paused")._value.get() == 1
    assert SWITCH.labels("push_disabled")._value.get() == 1
    assert SWITCH.labels("modules_paused")._value.get() == 1


async def test_module_config_endpoints(operator_client):
    base = "/api/zoho/admin/config/organizations"
    described = (await operator_client.get(base)).json()["data"]["knobs"]
    assert described["sync_interval_minutes"]["layer"] == "module"

    ok = await operator_client.put(f"{base}/max_pages_per_run", json={"value": 10, "reason": "slow CDC week"})
    assert ok.status_code == 200
    assert ok.json()["data"]["knobs"]["max_pages_per_run"] == {
        **ok.json()["data"]["knobs"]["max_pages_per_run"], "value": 10, "layer": "override"}

    refused = await operator_client.put(f"{base}/batch_size", json={"value": 5000, "reason": "go faster"})
    assert refused.status_code == 400 and "200" in refused.json()["msg"]

    cleared = await operator_client.delete(f"{base}/max_pages_per_run", params={"reason": "back to normal"})
    assert cleared.status_code == 200
    assert cleared.json()["data"]["knobs"]["max_pages_per_run"]["layer"] != "override"
    missing = await operator_client.delete(f"{base}/max_pages_per_run", params={"reason": "again"})
    assert missing.status_code == 404
