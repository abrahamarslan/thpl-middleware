"""Zoho OAuth connect flow: return URL rules, storage guard, callback (ERRORS E31/E32)."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import text

from app.core.conf import settings
from app.main import app
from app.modules.zoho.auth import service as auth_service
from app.modules.zoho.auth.service import ReturnUrlNotAllowed, resolve_return_url
from app.modules.zoho.core.auth import zoho_token_manager

CALLBACK = "https://app.local/api/zoho/auth/callback"


@pytest.fixture
def oauth_settings(monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_REDIRECT_URL", CALLBACK)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.local")
    monkeypatch.setattr(settings, "ZOHO_AUTH_RETURN_URL", "")
    monkeypatch.setattr(settings, "ZOHO_AUTH_RETURN_HOSTS", "")
    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(settings, "ZOHO_TOKEN_ENCRYPTION_KEY", "test-key-for-oauth-flow-0123456789")
    monkeypatch.setattr(settings, "ZOHO_AUTH_REQUIRE_USER", False)
    monkeypatch.setattr(settings, "ZOHO_CALLBACK_REQUIRE_USER", False)


# ── return URL rules (pure) ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, None),                                            # nothing configured → JSON answer
        ("", None),
        (CALLBACK, None),                                        # the callback itself → never (E31 loop)
        ("https://app.local/api/zoho/auth/callback/", None),
        ("/settings/integrations", "/settings/integrations"),    # a path on this site
        ("https://app.local/settings?tab=zoho", "https://app.local/settings?tab=zoho"),
    ],
)
def test_return_url_resolution(oauth_settings, requested, expected):
    assert resolve_return_url(requested) == expected


def test_configured_default_is_used(oauth_settings, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_AUTH_RETURN_URL", "https://app.local/zoho/connected")
    assert resolve_return_url(None) == "https://app.local/zoho/connected"


@pytest.mark.parametrize("bad", ["https://evil.example/steal", "//evil.example/x", "javascript:alert(1)",
                                 "ftp://app.local/x", "settings"])
def test_open_redirects_are_refused(oauth_settings, bad):
    with pytest.raises(ReturnUrlNotAllowed):
        resolve_return_url(bad)


def test_extra_hosts_can_be_allowed(oauth_settings, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_AUTH_RETURN_HOSTS", "admin.tarrinahealth.com")
    assert resolve_return_url("https://admin.tarrinahealth.com/x") == "https://admin.tarrinahealth.com/x"


# ── endpoints ───────────────────────────────────────────────────────────────

@pytest.fixture
async def api(db, redis_available, oauth_settings):
    from app.database.db import get_db

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    zoho_token_manager.store.invalidate_cache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.local") as client:
        yield client
    app.dependency_overrides.clear()
    zoho_token_manager.store.invalidate_cache()
    from app.database.db import engine

    await engine.dispose()


async def test_initiate_refuses_when_the_token_could_not_be_kept(api, monkeypatch):
    monkeypatch.setattr(settings, "ZOHO_TOKEN_PERSISTENCE_ENABLED", False)
    response = await api.get("/api/zoho/auth/initiate", params={"redirect": "false"})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "zoho_token_storage_not_configured"
    assert "ZOHO_TOKEN_ENCRYPTION_KEY" in body["msg"]


async def test_callback_without_code_explains_instead_of_422(api):
    response = await api.get("/api/zoho/auth/callback")
    assert response.status_code == 400
    assert response.json()["code"] == "zoho_consent_failed"
    assert "/api/zoho/auth/initiate" in response.json()["msg"]

    denied = await api.get("/api/zoho/auth/callback", params={"error": "access_denied"})
    assert denied.status_code == 400 and "access_denied" in denied.json()["msg"]


def zoho_token_endpoint(monkeypatch, seen: list[dict]):
    """The accounts server's /oauth/v2/token, answering a code exchange."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"access_token": "1000.access", "refresh_token": "1000.refresh-secret",
                                          "expires_in": 3600, "api_domain": "https://www.zohoapis.in",
                                          "token_type": "Bearer", "scope": settings.ZOHO_SCOPE})

    real = httpx.AsyncClient

    class ZohoAccounts(real):
        def __init__(self, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(auth_service.httpx, "AsyncClient", ZohoAccounts)


async def start(api, **params) -> str:
    response = await api.get("/api/zoho/auth/initiate", params={"redirect": "false", **params})
    assert response.status_code == 200, response.text
    url = response.json()["data"]["authorization_url"]
    query = parse_qs(urlsplit(url).query)
    assert query["redirect_uri"] == [CALLBACK]
    return query["state"][0]


async def test_full_connect_answers_json_and_stores_the_token_encrypted(api, db, monkeypatch):
    seen: list[dict] = []
    # Swagger users typed the callback URL as return_url — exactly the E31 loop.
    state = await start(api, return_url=CALLBACK)
    zoho_token_endpoint(monkeypatch, seen)

    response = await api.get("/api/zoho/auth/callback", params={"code": "1000.code", "state": state})
    assert response.status_code == 200, response.text          # JSON, not a redirect back to itself
    assert response.json()["data"] == {"connected": True, "persisted": True}
    assert seen[0]["grant_type"] == "authorization_code" and seen[0]["redirect_uri"] == CALLBACK

    stored = (await db.execute(text("SELECT refresh_token_enc FROM zoho_oauth_credentials"))).scalar_one()
    assert b"1000.refresh-secret" not in bytes(stored)          # encrypted at rest
    zoho_token_manager.store.invalidate_cache()
    assert await zoho_token_manager.get_refresh_token() == "1000.refresh-secret"   # readable by any process
    status = await api.get("/api/zoho/auth/status")
    assert status.json()["data"]["is_connected"] is True

    replay = await api.get("/api/zoho/auth/callback", params={"code": "1000.code", "state": state})
    assert replay.status_code == 401                            # state is single-use


async def test_connect_redirects_to_the_frontend_page(api, monkeypatch):
    state = await start(api, return_url="/settings/integrations?zoho=connected")
    zoho_token_endpoint(monkeypatch, [])
    response = await api.get("/api/zoho/auth/callback", params={"code": "1000.code", "state": state})
    assert response.status_code == 307
    assert response.headers["location"] == "/settings/integrations?zoho=connected"
