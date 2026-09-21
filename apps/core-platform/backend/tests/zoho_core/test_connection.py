"""GET /api/zoho/auth/connection — can we sync, and if not, why? (real transport, mocked wire)."""

import httpx
import pytest

from app.core.conf import settings
from app.modules.zoho.control.switches import SwitchState, zoho_switches
from app.modules.zoho.core import connection
from app.modules.zoho.core import transport as transport_module
from app.modules.zoho.core.auth import Credential, CredentialUnavailable, zoho_token_manager
from app.modules.zoho.core.governor import zoho_governor

ORG_ID = "60015628348"


class Wire:
    def __init__(self, *, wrong_org: bool = False):
        self.calls: list[str] = []
        self.wrong_org = wrong_org

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        if self.wrong_org:
            return httpx.Response(400, json={"code": 6041, "message":
                                             "This user is not associated with the CompanyID/CompanyName:60059694101."})
        return httpx.Response(200, json={"code": 0, "message": "success", "organization": {
            "organization_id": ORG_ID, "name": "Tarrina Health Private Limited", "currency_code": "INR"}})


class StubTokens:
    async def get_token(self):
        return "t"

    async def invalidate(self, token=None):
        pass


@pytest.fixture
async def env(redis_available, monkeypatch):
    for key in ("zoho:conn:last_ok", "zoho:conn:last_error", "zoho:conn:probe", "zoho:conn:probe:lock"):
        await redis_available.delete(key)
    async for key in redis_available.scan_iter(match="zoho:cb:*"):     # circuits other tests left open
        await redis_available.delete(key)
    connection._last_write["ok"] = 0.0
    monkeypatch.setattr(settings, "ZOHO_CLIENT_ID", "client")
    monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "ZOHO_ORGANIZATION_ID", ORG_ID)
    monkeypatch.setattr(settings, "ZOHO_REDIRECT_URL", "https://app.local/api/zoho/auth/callback")

    async def stored():
        return Credential("refresh", source="database", version=2)

    monkeypatch.setattr(zoho_token_manager.store, "load", stored)

    async def running():
        return SwitchState()

    monkeypatch.setattr(zoho_switches, "snapshot", running)
    await zoho_governor.reset_day()
    wire = Wire()

    class WiredClient(transport_module.ZohoClient):
        def __init__(self, **kwargs):
            super().__init__(http=httpx.AsyncClient(transport=httpx.MockTransport(wire)),
                             token_manager=StubTokens(), switches=_Open(), **kwargs)

    monkeypatch.setattr(transport_module, "ZohoClient", WiredClient)
    yield wire
    await zoho_governor.reset_day()


class _Open:
    async def check(self, **_):
        return None


def by_name(report):
    return {c["name"]: c for c in report["checks"]}


async def test_connected_with_one_probe_then_evidence_instead_of_calls(env):
    report = await connection.connection_report()
    assert report["can_sync"] is True and report["state"] == "connected"
    assert report["organization"]["name"] == "Tarrina Health Private Limited"
    assert env.calls == [f"/books/v3/organizations/{ORG_ID}"]

    again = await connection.connection_report()                       # auto: recent success → no call
    assert again["can_sync"] is True and env.calls == [f"/books/v3/organizations/{ORG_ID}"]
    assert by_name(again)["recent_traffic"]["status"] == "ok"

    forced = await connection.connection_report(probe="always")         # cached for 60 s
    assert by_name(forced)["live_probe"]["data"]["cached"] is True and len(env.calls) == 1


async def test_wrong_organization_id_is_misconfigured_with_the_fix(env):
    env.wrong_org = True
    report = await connection.connection_report()
    assert report["can_sync"] is False and report["state"] == "misconfigured"
    probe = by_name(report)["live_probe"]
    assert probe["status"] == "fail" and "ZOHO_ORGANIZATION_ID" in probe["detail"]
    assert report["last_error"]["zoho_code"] == 6041


async def test_missing_configuration_makes_no_call(env, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_CLIENT_SECRET", "")
    report = await connection.connection_report()
    assert report["state"] == "misconfigured" and "ZOHO_CLIENT_SECRET" in report["summary"]
    assert env.calls == []


async def test_not_connected_without_a_credential(env, monkeypatch):
    async def nothing():
        raise CredentialUnavailable("none")

    monkeypatch.setattr(zoho_token_manager.store, "load", nothing)
    report = await connection.connection_report()
    assert report["state"] == "not_connected" and "/api/zoho/auth/initiate" in report["summary"]
    assert env.calls == []


async def test_a_paused_engine_blocks_syncing_even_if_zoho_is_fine(env, monkeypatch):
    async def paused():
        return SwitchState(engine_paused=True)

    monkeypatch.setattr(zoho_switches, "snapshot", paused)
    report = await connection.connection_report()
    assert report["state"] == "blocked" and report["can_sync"] is False
    assert by_name(report)["switches"]["detail"] == "engine paused by an operator"


async def test_never_probe_is_free(env):
    report = await connection.connection_report(probe="never")
    assert env.calls == [] and "live_probe" not in by_name(report)


async def test_endpoint_is_mounted(env, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "ZOHO_AUTH_REQUIRE_USER", False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/zoho/auth/connection", params={"probe": "never"})
    assert response.status_code == 200 and response.json()["data"]["state"] in ("connected", "degraded")
